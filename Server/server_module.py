"""Aurex WSS marketplace server.

This module keeps transport concerns (WebSocket framing), command routing,
and domain actions separate so networking changes do not leak into business
logic handlers.
"""

import asyncio
import base64
import datetime
import json
import hashlib
import os
import queue
import random
import re
import socket
import ssl as ssl_module
import struct
import sys
import threading
import time
import shutil
import uuid
import urllib.error
import urllib.request
from importlib import util as importlib_util
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import websockets
from websockets.exceptions import ConnectionClosed
from aurex_logging import AurexLogger

try:
    from protocol_definitions import (
        GET_ASSET_BINARY_PREFIX,
        UPLOAD_CHUNK_PREFIX,
        DiscoveryRequest,
        DiscoveryResponse,
        ProtocolCommand,
        ProtocolPrefix,
        parse_wire_message,
        serialize_command,
        serialize_event,
        serialize_response,
    )
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from protocol_definitions import (
        GET_ASSET_BINARY_PREFIX,
        UPLOAD_CHUNK_PREFIX,
        DiscoveryRequest,
        DiscoveryResponse,
        ProtocolCommand,
        ProtocolPrefix,
        parse_wire_message,
        serialize_command,
        serialize_event,
        serialize_response,
    )
try:
    from Server.config import (
        SERVER_HOST, SERVER_PORT, SERVER_IP,
        BROADCAST_PORT, SSL_CERT_FILE, SSL_KEY_FILE,
        BLOCK_CONFIRMATION_PORT,
        GATEWAY_HOST, GATEWAY_PORT,
        ENABLE_UDP_DISCOVERY,
        UPLOADS_DIR,
        UPLOAD_TMP_DIR, UPLOAD_CHUNK_SIZE,
        TX_TIME_WINDOW_SECONDS,
        FCM_ENABLED, FCM_SERVER_KEY,
    )
    from Server.classes import PROTO
    from Server.DB_ORM import MarketplaceDB, send_reset_email
except ModuleNotFoundError:
    # Allow running this file directly from the Server folder:
    #   python server_module.py
    from config import (
        SERVER_HOST, SERVER_PORT, SERVER_IP,
        BROADCAST_PORT, SSL_CERT_FILE, SSL_KEY_FILE,
        BLOCK_CONFIRMATION_PORT,
        GATEWAY_HOST, GATEWAY_PORT,
        ENABLE_UDP_DISCOVERY,
        UPLOADS_DIR,
        UPLOAD_TMP_DIR, UPLOAD_CHUNK_SIZE,
        TX_TIME_WINDOW_SECONDS,
        FCM_ENABLED, FCM_SERVER_KEY,
    )
    from classes import PROTO
    from DB_ORM import MarketplaceDB, send_reset_email
from cryptography.hazmat.primitives.asymmetric import ed25519

_UPLOADS_DIR_PATH = (Path(__file__).parent / UPLOADS_DIR).resolve()
_UPLOADS_DIR_PATH.mkdir(parents=True, exist_ok=True)

server_logger = AurexLogger.get_logger(__name__)


def _read_image_bytes(filename: str, max_width: int = 400) -> bytes | None:
    path = _resolve_upload_file(filename)
    if path is None:
        return None
    try:
        return path.read_bytes()
    except Exception:
        return None


def _resolve_upload_file(filename: str) -> Path | None:
    rel_name = (filename or "").strip().replace("\\", "/")
    if not rel_name:
        return None
    rel_path = Path(rel_name)
    if rel_path.is_absolute() or any(part in ("", ".", "..") for part in rel_path.parts):
        return None
    try:
        resolved = (_UPLOADS_DIR_PATH / rel_path).resolve()
        resolved.relative_to(_UPLOADS_DIR_PATH)
    except Exception:
        return None
    return resolved


def _safe_asset_filename(name: str, extension: str, fallback: str = "asset") -> str:
    raw_name = Path(name or "").stem if name else ""
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", raw_name).strip("._")
    if not safe_stem:
        safe_stem = fallback
    normalized_ext = (extension or "").strip().lower().lstrip(".")
    return f"{safe_stem}.{normalized_ext}" if normalized_ext else safe_stem


def _canonical_tx_message(sender, data):
    payload = {"sender": sender, "data": data}
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()


def _verify_ed25519_signature(public_key_b64, message_bytes, signature_b64):
    try:
        public_key_raw = base64.b64decode(public_key_b64.encode())
        signature_raw = base64.b64decode(signature_b64.encode())
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_raw)
        public_key.verify(signature_raw, message_bytes)
        return True
    except Exception:
        return False


def _is_timestamp_valid(ts_str):
    if not ts_str:
        return False
    try:
        ts_str = ts_str.replace('Z', '+00:00')
        ts = datetime.datetime.fromisoformat(ts_str)
        now = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        delta = abs((now - ts.replace(tzinfo=None)).total_seconds())
        return delta <= TX_TIME_WINDOW_SECONDS
    except Exception:
        return False


def _sha256_file(path):
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _resolve_path(path_value: str) -> str:
    path_obj = Path(path_value)
    if not path_obj.is_absolute():
        path_obj = (Path(__file__).parent / path_obj).resolve()
    return str(path_obj)


def _detect_local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            local_ip = sock.getsockname()[0]
            if local_ip:
                return local_ip
    except Exception:
        pass
    return "127.0.0.1"


def _resolve_server_ip(config_ip: str, bind_host: str) -> str:
    candidate = (config_ip or "").strip()
    if candidate and candidate not in ("0.0.0.0", "127.0.0.1", "localhost"):
        return candidate
    if bind_host and bind_host not in ("0.0.0.0", "127.0.0.1", "localhost"):
        return bind_host
    return _detect_local_ip()


def _normalize_remote_address(remote_address) -> tuple[str, int]:
    if isinstance(remote_address, tuple) and len(remote_address) >= 2:
        return str(remote_address[0]), int(remote_address[1])
    if remote_address:
        return str(remote_address), 0
    return "unknown", 0


def _load_blockchain_notifications_manager():
    classes_path = (Path(__file__).parent.parent / "blockchain" / "classes.py").resolve()
    spec = importlib_util.spec_from_file_location("blockchain_classes", classes_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load blockchain classes from {classes_path}")
    module = importlib_util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NotificationsManager


NotificationsManager = _load_blockchain_notifications_manager()


@dataclass
class UploadSession:
    """Track a chunked upload session per client."""
    upload_id: str
    username: str
    asset_name: str
    description: str
    file_type: str
    cost: float
    file_size: int
    original_name: str
    temp_path: str
    asset_hash: str = ''
    mint_tx_id: str = ''
    mint_timestamp: str = ''
    public_key: str = ''
    mint_signature: str = ''
    total_chunks: int = 0
    received_chunks: int = 0
    next_seq: int = 0
    bytes_received: int = 0
    created_at: float = field(default_factory=time.time)


class ClientSession:
    """Represents one authenticated client connection"""
    def __init__(self, sock, addr, server, loop):
        self.socket = sock
        self.address = addr
        self.server = server
        
        self.proto = PROTO(cln_sock=sock, loop=loop)
        self.logger = AurexLogger.get_logger(__name__)
        
        self.username = None
        self.server.unregister_session(self)
        self.is_authenticated = False
        self.is_connected = True
        self.db = MarketplaceDB()  # ORM: DB/marketplace.db (users + marketplace_items)
        self.notifications_manager = server.notifications_manager
        self.create_and_push_notification = server.create_and_push_notification

        # Ensure upload temp directory exists
        self.upload_tmp_dir = Path(UPLOAD_TMP_DIR)
        if not self.upload_tmp_dir.is_absolute():
            self.upload_tmp_dir = (Path(__file__).parent / self.upload_tmp_dir).resolve()
        self.upload_tmp_dir.mkdir(parents=True, exist_ok=True)

        self.handlers = {
            ProtocolCommand.START.value: self.handle_start,
            ProtocolCommand.LOGIN.value: self.handle_login,
            ProtocolCommand.SIGNUP.value: self.handle_signup,
            ProtocolCommand.SEND_CODE.value: self.handle_send_code,
            ProtocolCommand.VERIFY_CODE.value: self.handle_verify_code,
            ProtocolCommand.UPDATE_PASSWORD.value: self.handle_update_password,
            ProtocolCommand.LOGOUT.value: self.handle_logout,
            ProtocolCommand.UPLOAD.value: self.handle_log_asset,
            ProtocolCommand.UPLOAD_INIT.value: self.handle_upload_init,
            ProtocolCommand.UPLOAD_FINISH.value: self.handle_upload_finish,
            ProtocolCommand.UPLOAD_ABORT.value: self.handle_upload_abort,
            ProtocolCommand.GET_ASSET_BINARY.value: self.handle_get_asset_binary,
            ProtocolCommand.GET_ITEMS.value: self.handle_asset_list,
            ProtocolCommand.GET_ITEMS_PAGINATED.value: self.handle_get_items_paginated,
            ProtocolCommand.BUY.value: self.handle_buy_asset,
            ProtocolCommand.SEND.value: self.handle_send_asset,
            ProtocolCommand.GET_PROFILE.value: self.handle_get_profile,
            ProtocolCommand.GET_TX_STATUS.value: self.handle_get_tx_status,
            ProtocolCommand.GET_ITEMS_BY_USER.value: self.handle_get_items_by_user,
            ProtocolCommand.GET_WALLET.value: self.handle_get_wallet,
            ProtocolCommand.GET_NOTIFICATIONS.value: self.handle_get_notifications,
            ProtocolCommand.MARK_NOTIFICATIONS_READ.value: self.handle_mark_notifications_read,
            ProtocolCommand.REGISTER_DEVICE.value: self.handle_register_device,
            ProtocolCommand.LIST_ITEM.value: self.handle_list_item,
            ProtocolCommand.UNLIST_ITEM.value: self.handle_unlist_item,
            ProtocolCommand.UPDATE_PUBLIC_KEY.value: self.handle_update_public_key,
        }
    
    def process_message(self, message):
        """Parse and handle incoming message"""
        try:
            parsed = parse_wire_message(message)
            command = parsed.head
            tail = list(parsed.parts)
            
            if command not in self.handlers:
                self.logger.error(f" Unknown command: {command}")
                self.logger.warning(f"   Available commands: {', '.join(self.handlers.keys())}")
                return f"ERR02|Unknown command: {command}"
            
            handler = self.handlers[command]
            self.logger.debug(f" Processing command: {command}")
            return handler(tail)
        except Exception as e:
            self.logger.error(f" Error processing message: {e}")
            return f"ERR99|{str(e)}"
    
    def handle_start(self, params):
        """Protocol Message 1: START - Initialize connection"""
        self.logger.info(" START message received - accepting connection")
        return serialize_response(ProtocolPrefix.ACCEPT, "Connection accepted")
    
    def handle_login(self, params):
        """Protocol Message: LOGIN - Username/Password authentication
        Format: LOGIN|username|password
        Returns: OK|username or ERR|error_message
        """
        if len(params) < 2:
            self.logger.error(" Invalid login format")
            return "ERR01|Invalid login format"
        
        username = params[0].strip()
        password = params[1].strip()
        
        # Validate username format
        if not username or '|' in username or ' ' in username:
            self.logger.error(f" Invalid username format: {username}")
            return "ERR01|Invalid username format"
        
        try:
            user_obj = self.db.get_user(username)
            if user_obj and user_obj.verify_password(password):
                self.username = username
                self.is_authenticated = True
                self.server.register_authenticated_session(self)
                self.logger.info(f" [RECV] LOGIN|{username}|***")
                self.logger.info(f" User {username} logged in")
                return f"OK|{username}"
            self.logger.error(f" Invalid credentials for {username}")
            return "ERR01|user not found"
        except Exception as e:
            self.logger.error(f" Login error: {e}")
            return f"ERR99|{str(e)}"
    
    def handle_signup(self, params):
        """Protocol Message: SIGNUP - User registration
        Format: SIGNUP|username|password|email
        Returns: OK|username or ERR|error_message
        """
        self.logger.info(
            f" [SIGNUP] handler entered params_count={len(params)} "
            f"has_public_key={len(params) >= 4}"
        )
        if len(params) < 3:
            self.logger.error(" Invalid signup format")
            return "ERR10|Invalid signup format: SIGNUP|username|password|email"
        
        username = params[0].strip()
        password = params[1].strip()
        email = params[2].strip().lower()
        
        # Validate fields - no pipes or spaces
        if '|' in username or '|' in password or '|' in email:
            self.logger.error(" Invalid characters in signup fields")
            return "ERR10|Fields cannot contain '|'"
        
        if username != params[0] or password != params[1]:
            self.logger.error(" Fields have leading/trailing spaces")
            return "ERR10|Fields cannot have leading/trailing spaces"
        
        # Validate inputs
        if not username or not password or not email:
            self.logger.error(" Missing required fields for signup")
            return "ERR10|Missing required fields"
        
        # Username validation: 3-20 chars, alphanumeric + underscore
        import re
        if not re.match(r'^[a-zA-Z0-9_]{3,20}$', username):
            self.logger.error(f" Invalid username format: {username}")
            return "ERR10|Username: 3-20 chars, alphanumeric + underscore only"
        
        # Password validation: min 6 chars
        if len(password) < 6:
            self.logger.error(" Password too short")
            return "ERR10|Password must be at least 6 characters"
        
        if ' ' in email or '@' not in email:
            return "ERR10|Invalid email format"

        # Explicit duplicate checks before insertion.
        if self.db.get_user(username):
            self.logger.error(f" Signup blocked: username already exists ({username})")
            return "ERR10|Username already exists"
        if self.db.get_user_by_email(email):
            self.logger.error(f" Signup blocked: email already exists ({email})")
            return "ERR10|Email already exists"

        public_key = params[3].strip() if len(params) >= 4 else None
        if public_key and "|" in public_key:
            return "ERR10|Invalid public key"
        self.logger.info(
            f" [SIGNUP] username={username} email={email} "
            f"public_key_len={len(public_key) if public_key else 0}"
        )

        success, message = self.db.add_user(username, password, email, public_key=public_key)
        if success:
            self.logger.info(f" User {username} signed up")
            return f"OK|{username}"
        self.logger.error(f" Signup failed: {message}")
        return f"ERR10|{message}"

    def handle_send_code(self, params):
        """Protocol Message: SEND_CODE - Send OTP code for password reset
        Format: SEND_CODE|email
        Returns: OK|otp_sent or ERR|error_message
        """
        if len(params) < 1:
            self.logger.error(" Invalid SEND_CODE format")
            return "ERR04|Invalid format: SEND_CODE|email"
        
        email = params[0].strip()
        
        if not email or '|' in email or ' ' in email:
            self.logger.error(" Invalid email format")
            return "ERR04|Invalid email format"
        user_obj = self.db.get_user_by_email(email)
        if not user_obj:
            self.logger.error(f" Email {email} not registered")
            return "ERR04|Email not found in system"
        now = datetime.datetime.now()
        if user_obj.verification_code and user_obj.reset_time:
            try:
                expiry = datetime.datetime.fromisoformat(user_obj.reset_time)
                if now < expiry:
                    self.logger.info(f" Reusing existing reset code for {email}")
                    # Re-send the existing OTP via email (don't expose it in the response)
                    otp_to_send = user_obj.verification_code
                    import threading as _t
                    _t.Thread(
                        target=send_reset_email,
                        args=(email, otp_to_send),
                        daemon=True,
                    ).start()
                    return "OK|otp_sent"
            except Exception:
                pass
        otp = str(random.randint(100000, 999999))
        user_obj.set_verification_code(otp)
        user_obj.set_reset_time((datetime.datetime.now() + datetime.timedelta(minutes=5)).isoformat())
        self.db.update_user(user_obj.username, user_obj)
        self.logger.info(f" Generated reset code for {email}")
        # Send OTP via email in background thread — never expose it in the protocol response.
        import threading as _t
        _t.Thread(target=send_reset_email, args=(email, otp), daemon=True).start()
        return "OK|otp_sent"

    def handle_verify_code(self, params):
        """Protocol Message: VERIFY_CODE - Verify OTP code
        Format: VERIFY_CODE|email|otp_code
        Returns: OK|token or ERR|error_message
        """
        if len(params) < 2:
            self.logger.error(" Invalid VERIFY_CODE format")
            return "ERR08|Invalid format: VERIFY_CODE|email|otp_code"
        
        email = params[0].strip()
        otp_code = params[1].strip()
        
        if not email or not otp_code or '|' in email or '|' in otp_code:
            self.logger.error(" Invalid verify code inputs")
            return "ERR08|Invalid input format"
        user_obj = self.db.get_user_by_email(email)
        if not user_obj:
            self.logger.error(f" Email {email} not found")
            return "ERR08|Email not found"
        if user_obj.is_code_match_and_available(datetime.datetime.now(), otp_code):
            user_obj.is_verified = True
            self.db.update_user(user_obj.username, user_obj)
            self.logger.info(f" OTP verified for {email}")
            return f"OK|RESET_{user_obj.username}_{int(time.time())}"
        self.logger.error(f" Invalid or expired OTP for {email}")
        return "ERR08|Invalid or expired OTP"

    def handle_update_password(self, params):
        """Protocol Message: UPDATE_PASSWORD - Change user password (after OTP verification)
        Format: UPDATE_PASSWORD|email|new_password
        Returns: OK or ERR|error_message
        """
        if len(params) < 2:
            self.logger.error(" Invalid UPDATE_PASSWORD format")
            return "ERR07|Invalid format: UPDATE_PASSWORD|email|new_password"
        
        email = params[0].strip()
        new_password = params[1].strip()
        
        if not email or not new_password or '|' in email or '|' in new_password:
            self.logger.error(" Invalid password update inputs")
            return "ERR07|Invalid input format"
        if len(new_password) < 6:
            self.logger.error(" New password too short")
            return "ERR07|Password must be at least 6 characters"
        user_obj = self.db.get_user_by_email(email)
        if not user_obj:
            self.logger.error(f" Email {email} not found")
            return "ERR07|Email not found"
        user_obj.set_password(new_password)
        self.db.update_user(user_obj.username, user_obj)
        self.logger.info(f" Password updated for {email}")
        return "OK|Password updated successfully"

    def handle_logout(self, params):
        """Protocol Message: LOGOUT - End authenticated session.
        Format: LOGOUT|username
        Returns: OK|logged_out
        NOTE: Was returning EXTLG (inconsistent). Fixed to OK for protocol uniformity.
        """
        self.is_authenticated = False
        username = self.username
        self.username = None
        self.logger.info(f" User {username} logged out")
        return "OK|logged_out"

    def _normalize_file_type(self, file_type: str) -> str:
        """Normalize file type to a supported extension."""
        normalized = (file_type or "").strip().lower()
        if normalized == "jpeg":
            normalized = "jpg"
        if normalized == "image":
            normalized = "jpg"
        return normalized

    def _validate_file_signature(self, file_type: str, first_bytes: bytes) -> bool:
        """Validate PNG/JPG magic bytes."""
        if file_type == "png":
            return first_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        if file_type == "jpg":
            return first_bytes.startswith(b"\xff\xd8\xff")
        return False

    def _cleanup_upload(self, upload_id: str) -> None:
        """Remove temp file and session data for a given upload."""
        with self.server.upload_sessions_lock:
            session = self.server.upload_sessions.pop(upload_id, None)
        if not session:
            return
        try:
            if os.path.exists(session.temp_path):
                os.remove(session.temp_path)
        except Exception:
            pass
    
    def handle_log_asset(self, params):
        """Protocol Message: UPLOAD - Legacy direct-URL upload
        Format: UPLOAD|asset_name|username|google_drive_url|file_type|cost
        """
        return "ERR01|Legacy upload disabled. Use chunked upload (UPLOAD_INIT)."
        if not self.is_authenticated:
            return "ERR03|Not authenticated"
        
        if len(params) < 5:
            self.logger.error(f"[RECV] UPLOAD - Invalid format, got {len(params)} params")
            return "ERR01|Invalid format: UPLOAD|asset_name|username|url|file_type|cost"
        
        try:
            asset_name = params[0].strip()
            username = params[1].strip()
            url = params[2].strip()
            file_type = params[3].strip()
            cost = float(params[4].strip())
            
            # Ensure authenticated user is uploading for their own account
            if username != self.username:
                return "ERR02|Cannot upload on behalf of another user"
            
            # Validate inputs
            if not asset_name or not username or not url or not file_type or cost < 0:
                return "ERR01|Invalid parameters"
            
            normalized_type = self._normalize_file_type(file_type)
            if normalized_type not in ['jpg', 'png']:
                return "ERR01|Invalid file type. Supported: jpg, png"
            
            # Add to marketplace database (ORM: DB/marketplace.db)
            marketplace_db = MarketplaceDB()
            success, message, item_id = marketplace_db.add_marketplace_item(
                asset_name,
                username,
                url,
                normalized_type,
                cost,
            )
            
            if success:
                self.logger.info(f" Asset uploaded: {asset_name} by {username} - \\${cost}")
                self.create_and_push_notification(
                    username=username,
                    title="Asset uploaded",
                    body=f"Your asset {asset_name} is now in the marketplace.",
                    notif_type="asset_uploaded",
                    asset_id=str(item_id) if item_id else None,
                )
                return f"OK|Asset '{asset_name}' uploaded successfully"
            else:
                self.logger.error(f" Failed to upload asset: {message}")
                return f"ERR03|{message}"
                
        except ValueError:
            return "ERR01|Invalid cost format"
        except Exception as e:
            self.logger.error(f" Error processing UPLOAD: {e}")
            return f"ERR99|{str(e)}"

    def handle_upload_init(self, params):
        """
        Protocol: UPLOAD_INIT - Start a chunked upload session.
        Format: UPLOAD_INIT|base64(json)
        Response: OK|upload_id|chunk_size or ERR|message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: UPLOAD_INIT|base64(json)"
        try:
            payload = base64.b64decode(params[0].encode("utf-8"))
            data = json.loads(payload.decode("utf-8"))
        except Exception:
            return "ERR01|Invalid init payload"

        asset_name = str(data.get("asset_name", "")).strip()
        username = str(data.get("username", "")).strip()
        description = str(data.get("description", "")).strip()
        file_type = self._normalize_file_type(data.get("file_type", ""))
        original_name = str(data.get("original_name", "")).strip()
        file_size = int(data.get("file_size", 0) or 0)
        asset_hash = str(data.get("asset_hash", "")).strip()
        mint_tx_id = str(data.get("mint_tx_id", "")).strip()
        mint_timestamp = str(data.get("mint_timestamp", "")).strip()
        public_key = str(data.get("public_key", "")).strip()
        mint_signature = str(data.get("mint_signature", "")).strip()
        try:
            cost = float(data.get("cost", 0))
        except Exception:
            cost = -1

        if username != self.username:
            return "ERR02|Unauthorized"
        if not asset_name or not username or cost <= 0 or file_size <= 0:
            return "ERR01|Invalid parameters"
        if file_type not in ("jpg", "png"):
            return "ERR01|Invalid file type. Supported: jpg, png"
        if not asset_hash or not mint_tx_id or not mint_timestamp or not public_key or not mint_signature:
            return "ERR01|Missing mint signature data"
        if not _is_timestamp_valid(mint_timestamp):
            return "ERR01|Invalid mint timestamp"
        with self.server.tx_status_lock:
            if mint_tx_id in self.server.tx_status:
                return "ERR02|Duplicate mint tx_id"
        mint_payload = {
            "action": "asset_mint",
            "tx_id": mint_tx_id,
            "asset_hash": asset_hash,
            "asset_name": asset_name,
            "file_name": original_name or f"{asset_name}.{file_type}",
            "owner": username,
            "owner_pub": public_key,
            "cost": cost,
            "timestamp": mint_timestamp,
        }
        wallet = self.db.get_wallet(username)
        if wallet and float(wallet.get('balance', 0)) < cost:
            pass
        if not _verify_ed25519_signature(
            public_key,
            _canonical_tx_message(username, mint_payload),
            mint_signature,
        ):
            return "ERR02|Invalid mint signature"
        if not self.db.set_user_public_key(username, public_key, force_update=True):
            return "ERR02|Failed to store public key"
        self.db.register_wallet(username, public_key)

        upload_id = uuid.uuid4().hex
        temp_path = str(self.upload_tmp_dir / f"upload_{upload_id}.bin")
        try:
            self.upload_tmp_dir.mkdir(parents=True, exist_ok=True)
            with open(temp_path, "wb"):
                pass
        except OSError as e:
            return f"ERR99|Cannot create upload temp file: {e}"

        session = UploadSession(
            upload_id=upload_id,
            username=username,
            asset_name=asset_name,
            description=description,
            file_type=file_type,
            cost=cost,
            file_size=file_size,
            original_name=original_name or f"{asset_name}.{file_type}",
            temp_path=temp_path,
            asset_hash=asset_hash,
            mint_tx_id=mint_tx_id,
            mint_timestamp=mint_timestamp,
            public_key=public_key,
            mint_signature=mint_signature,
        )
        with self.server.upload_sessions_lock:
            self.server.upload_sessions[upload_id] = session

        return f"OK|{upload_id}|{UPLOAD_CHUNK_SIZE}"

    def _handle_binary_chunk_inline(self, upload_id: str, seq: int, chunk_bytes: bytes) -> str:
        """
        Internal handler for raw binary upload chunks.
        Called directly from handle_client when a framed message starts with b"UPLOAD_CHUNK|".
        Format (payload bytes): b"UPLOAD_CHUNK|" + upload_id + b"|" + 4-byte-seq-big-endian + raw-data
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if not upload_id or upload_id == "[]":
            return "ERR|INVALID_ID"
        with self.server.upload_sessions_lock:
            session = self.server.upload_sessions.get(upload_id)
        if not session:
            self.logger.error(f" ERR04: upload_id={upload_id!r} not found")
            return "ERR|INVALID_ID"
        if session.username != self.username:
            return "ERR02|Unauthorized"
        if seq != session.next_seq:
            return f"ERR05|Out of order chunk (expected {session.next_seq}, got {seq})"
        if seq == 0 and not self._validate_file_signature(session.file_type, chunk_bytes):
            self._cleanup_upload(upload_id)
            return "ERR06|Invalid file signature"
        session.bytes_received += len(chunk_bytes)
        if session.bytes_received > session.file_size:
            self._cleanup_upload(upload_id)
            return "ERR06|File size exceeded"
        try:
            with open(session.temp_path, "ab") as fh:
                fh.write(chunk_bytes)
                fh.flush()
        except Exception as e:
            self._cleanup_upload(upload_id)
            return f"ERR99|Write failed: {e}"
        session.received_chunks += 1
        session.next_seq += 1
        return f"OK|{seq}"

    def handle_get_asset_binary(self, params):
        """
        GET_ASSET_BINARY - Binary stream download of a stored asset image.
        Format: GET_ASSET_BINARY|username/filename.jpg
        Response: ASSET_START|size (text frame), then one raw binary frame of JPEG bytes.
        Returns None so handle_client skips the default send.
        """
        if not params or not params[0].strip():
            return "ERR01|Invalid format: GET_ASSET|relative/path.jpg"
        rel_path = params[0].strip()
        data = _read_image_bytes(rel_path)
        if data is None:
            return "ERR05|Asset not found or unreadable"
        self.proto.send_one_message(
            serialize_response(ProtocolPrefix.ASSET_START, len(data)).encode()
        )
        self.proto.send_one_message(data)
        return None  # handle_client must not send an additional response

    def handle_upload_finish(self, params):
        """
        Protocol: UPLOAD_FINISH - Finalize upload, move to user storage, register asset.
        Format: UPLOAD_FINISH|upload_id
        Response: OK|asset_name|relative_path or ERR|message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: UPLOAD_FINISH|upload_id"

        upload_id = params[0].strip()
        with self.server.upload_sessions_lock:
            session = self.server.upload_sessions.get(upload_id)
        if not session:
            return "ERR04|Upload session not found"
        if session.username != self.username:
            return "ERR02|Unauthorized"

        try:
            actual_size = os.path.getsize(session.temp_path)
        except OSError:
            actual_size = 0
        if actual_size != session.file_size:
            self._cleanup_upload(upload_id)
            return "ERR06|File size mismatch"
        if session.bytes_received != session.file_size:
            self._cleanup_upload(upload_id)
            return "ERR06|Byte count mismatch"
        try:
            actual_hash = _sha256_file(session.temp_path)
        except Exception:
            self._cleanup_upload(upload_id)
            return "ERR06|Hash calculation failed"
        if session.asset_hash and actual_hash != session.asset_hash:
            self._cleanup_upload(upload_id)
            return "ERR06|Asset hash mismatch"

        user_dir = _UPLOADS_DIR_PATH / session.username
        user_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_asset_filename(
            session.original_name or session.asset_name,
            session.file_type,
            fallback=session.asset_name or "asset",
        )
        local_filename = f"{upload_id[:8]}_{safe_name}"
        dest_path = user_dir / local_filename
        local_rel_path = f"{session.username}/{local_filename}"  # relative path stored in DB
        try:
            shutil.move(str(session.temp_path), str(dest_path))
        except Exception as e:
            self._cleanup_upload(upload_id)
            self.binary_upload_id = None
            return f"ERR03|Local storage failed: {e}"
        drive_url = local_rel_path  # stored in DB url column as username/filename

        try:
            marketplace_db = MarketplaceDB()
            success, message, item_id = marketplace_db.add_pending_asset(
                session.asset_name,
                session.username,
                drive_url,
                session.file_type,
                session.cost,
                session.description,
                actual_hash,
                session.public_key,
            )
        except Exception as e:
            self._cleanup_upload(upload_id)
            return f"ERR03|DB error: {e}"

        self._cleanup_upload(upload_id)
        if not success:
            return f"ERR03|{message}"
        self.logger.info(f" Asset uploaded: {session.asset_name} by {session.username} - ${session.cost}")
        # Queue mint transaction to blockchain

        mint_job = {
            'tx_type': 'mint',
            'tx_id': session.mint_tx_id,
            'owner': session.username,
            'asset_hash': actual_hash,
            'asset_name': session.asset_name,
            'asset_id': str(item_id) if item_id else None,
            'metadata_link': local_rel_path,
            'file_name': session.original_name or f"{session.asset_name}.{session.file_type}",
            'timestamp': session.mint_timestamp,
            'public_key': session.public_key,
            'signature': session.mint_signature,
            'cost': session.cost,
        }
        with self.server.tx_status_lock:
            if session.mint_tx_id in self.server.tx_status:
                self.server.tx_status[session.mint_tx_id]['status'] = 'failed'
                self.server.tx_status[session.mint_tx_id]['message'] = 'Duplicate mint tx_id'
            else:
                self.server.tx_status[session.mint_tx_id] = {
                    'tx_type': 'mint',
                    'status': 'queued',
                    'message': 'Queued for PoW mint',
                    'created_at': time.time(),
                    'asset_hash': actual_hash,
                    'asset_name': session.asset_name,
                    'asset_id': str(item_id) if item_id else None,
                    'owner': session.username,
                    'cost': session.cost,
                    'metadata_link': local_rel_path,
                    'file_name': session.original_name or f"{session.asset_name}.{session.file_type}",
                }
                self.server.tx_queue.put(mint_job)
        return f"OK|{session.asset_name}|{local_rel_path}|{session.mint_tx_id}"

    def handle_upload_abort(self, params):
        """
        Protocol: UPLOAD_ABORT - Cancel an in-progress upload.
        Format: UPLOAD_ABORT|upload_id
        """
        if len(params) < 1:
            return "ERR01|Invalid format: UPLOAD_ABORT|upload_id"
        upload_id = params[0].strip()
        self._cleanup_upload(upload_id)
        return "OK|Upload aborted"
    
    def handle_asset_list(self, params):
        """Protocol Message: GET_ITEMS - Get all marketplace items
        Format: GET_ITEMS
        Returns: OK|items_json or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"

        try:
            import json
            items = self.db.get_all_items()
            response = f"OK|{json.dumps(items)}"
            self.logger.info(f" GET_ITEMS: returned {len(items)} items")
            return response
        except Exception as e:
            self.logger.error(f"? Error processing GET_ITEMS: {e}")
            return f"ERR03|Error getting items: {str(e)}"

    def handle_get_items_paginated(self, params):
        """Protocol Message: GET_ITEMS_PAGINATED - Get marketplace items with pagination
        Format: GET_ITEMS_PAGINATED|limit[|lastTimestamp] (lastTimestamp = ISO string from last item)
        """
        import json
        
        if len(params) < 1:
            self.logger.error("[RECV] GET_ITEMS_PAGINATED - Invalid format")
            return "ERR01|Invalid format"
        
        try:
            limit = int(params[0].strip())
            lastTimestamp = params[1].strip() if len(params) > 1 and params[1].strip() else None
            
            self.logger.info(f"[RECV] GET_ITEMS_PAGINATED|{limit}|{lastTimestamp}")
            
            try:
                db = MarketplaceDB()
                if lastTimestamp:
                    items = db.get_items_before_timestamp(lastTimestamp, limit)
                else:
                    items = db.get_latest_items(limit)
                
                if items:
                    items_list = items if isinstance(items[0], dict) else [
                        {'id': r[0], 'asset_name': r[1], 'description': r[2], 'username': r[3], 'url': r[4],
                         'file_type': r[5], 'cost': r[6], 'asset_hash': r[7], 'timestamp': r[8], 'created_at': r[9],
                         'is_listed': r[10]}
                        for r in items
                    ]
                    response = f"OK|{json.dumps(items_list)}"
                    self.logger.info(f"[SEND] OK|{len(items_list)} items")
                    return response
                response = "OK|[]"
                self.logger.info("[SEND] OK|0 items (no more items)")
                return response
            except Exception as db_error:
                self.logger.error(f" Database error: {db_error}")
                return f"ERR03|Database error: {str(db_error)}"
        except ValueError as ve:
            self.logger.error(f"[RECV] GET_ITEMS_PAGINATED - Invalid parameters: {ve}")
            return "ERR01|Invalid parameters"
        except Exception as e:
            self.logger.error(f" Error processing GET_ITEMS_PAGINATED: {e}")
            return f"ERR99|{str(e)}"

    def handle_buy_asset(self, params):
        """
        BUY - Purchase an asset from marketplace
        Format: BUY|asset_id|username|amount|tx_id|timestamp|public_key|signature
        """
        if not self.is_authenticated:
            return "ERR03|Not authenticated"
        if len(params) < 7:
            self.logger.error("[RECV] BUY - Invalid format")
            return "ERR01|Invalid format: BUY|asset_id|username|amount|tx_id|timestamp|public_key|signature"

        try:
            asset_id = params[0].strip()
            requested_username = params[1].strip()
            username = (self.username or "").strip()
            amount = float(params[2].strip())
            tx_id = params[3].strip()
            timestamp = params[4].strip()
            public_key = params[5].strip()
            signature = params[6].strip()

            self.logger.info(
                f" Processing purchase: session_user={username} requested_user={requested_username} "
                f"asset={asset_id} amount={amount}"
            )

            if requested_username and requested_username != username:
                return "ERR02|Cannot purchase on behalf of another user"

            item = self.db.get_item_by_id(asset_id)
            if not item:
                return "ERR02|Asset not found"

            seller = (item.get('username') or "").strip()
            self.logger.info(f" BUY ownership check: buyer={username} seller={seller} asset={asset_id}")
            if seller == username:
                return "ERR02|Cannot buy your own asset"

            price = float(item.get('cost', 0))
            if abs(price - amount) > 0.01:
                return "ERR02|Price mismatch"
            if item.get('is_listed') is not None and int(item.get('is_listed')) == 0:
                return "ERR02|Asset is no longer listed"

            wallet = self.db.get_wallet(username)
            if not wallet:
                return "ERR02|Wallet not found"
            if float(wallet.get('balance', 0)) < price:
                return "ERR02|Insufficient funds"

            if not tx_id or not timestamp or not public_key or not signature:
                return "ERR02|Missing signature parameters"
            if not _is_timestamp_valid(timestamp):
                return "ERR02|Invalid or stale timestamp"
            if not self.db.set_user_public_key(username, public_key):
                return "ERR02|Public key mismatch"

            asset_hash = item.get('asset_hash')
            if not asset_hash:
                return "ERR02|Asset missing verified hash"
            tx_payload = {
                'action': 'asset_purchase',
                'tx_id': tx_id,
                'asset_id': asset_id,
                'asset_hash': asset_hash,
                'asset_name': item.get('asset_name'),
                'buyer_pub': public_key,
                'price': price,
                'from': username,
                'to': seller,
                'amount': price,
                'timestamp': timestamp,
            }
            msg_bytes = _canonical_tx_message(username, tx_payload)
            if not _verify_ed25519_signature(public_key, msg_bytes, signature):
                return "ERR02|Invalid signature"

            purchase = {
                'tx_type': 'purchase',
                'tx_id': tx_id,
                'buyer': username,
                'seller': seller,
                'asset_id': asset_id,
                'asset_hash': asset_hash,
                'asset_name': item.get('asset_name'),
                'amount': price,
                'timestamp': timestamp,
                'public_key': public_key,
                'signature': signature,
            }

            with self.server.tx_status_lock:
                if tx_id in self.server.tx_status:
                    return "ERR02|Duplicate tx_id"
                self.server.tx_status[tx_id] = {
                    'status': 'queued',
                    'message': 'Queued for PoW',
                    'created_at': time.time(),
                    'asset_id': asset_id,
                    'asset_name': item.get('asset_name'),
                    'buyer': username,
                    'seller': seller,
                    'amount': price,
                    'tx_type': 'purchase',
                }
            self.server.tx_queue.put(purchase)

            self.logger.info(f" Purchase queued for PoW: {tx_id}")
            return f"OK|PENDING|{tx_id}"

        except ValueError as ve:
            self.logger.error(f"[RECV] BUY - Invalid parameters: {ve}")
            return "ERR01|Invalid amount format"
        except Exception as e:
            self.logger.error(f" Error processing BUY: {e}")
            return f"ERR99|{str(e)}"

    def handle_send_asset(self, params):
        """
        SEND - Send purchased asset to another user
        Format: SEND|asset_id|sender_username|receiver_username|tx_id|timestamp|public_key|signature
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 7:
            self.logger.error("[RECV] SEND - Invalid format")
            return "ERR01|Invalid format: SEND|asset_id|sender|receiver|tx_id|timestamp|public_key|signature"
        
        try:
            asset_id = params[0].strip()
            sender_username = params[1].strip()
            receiver_username = params[2].strip()
            tx_id = params[3].strip()
            timestamp = params[4].strip()
            public_key = params[5].strip()
            signature = params[6].strip()

            if not asset_id or not sender_username or not receiver_username:
                return "ERR01|Invalid parameters"
            if sender_username != self.username:
                return "ERR02|Unauthorized"
            if sender_username == receiver_username:
                return "ERR02|Cannot send to yourself"

            item = self.db.get_item_by_id(asset_id)
            if not item:
                return "ERR02|Asset not found"
            if item.get('username') != sender_username:
                return "ERR02|Sender does not own asset"
            if item.get('is_listed') is not None and int(item.get('is_listed')) == 1:
                return "ERR02|Asset is listed for sale. Unlist before sending"

            receiver = self.db.get_user(receiver_username)
            if not receiver:
                return "ERR02|Receiver not found"

            if not tx_id or not timestamp or not public_key or not signature:
                return "ERR02|Missing signature parameters"
            if not _is_timestamp_valid(timestamp):
                return "ERR02|Invalid or stale timestamp"
            if not self.db.set_user_public_key(sender_username, public_key):
                return "ERR02|Public key mismatch"
            asset_hash = item.get('asset_hash')
            if not asset_hash:
                return "ERR02|Asset missing verified hash"
            tx_payload = {
                'action': 'asset_transfer',
                'tx_id': tx_id,
                'asset_id': asset_id,
                'asset_hash': asset_hash,
                'asset_name': item.get('asset_name'),
                'from': sender_username,
                'to': receiver_username,
                'amount': 0,
                'timestamp': timestamp,
            }
            msg_bytes = _canonical_tx_message(sender_username, tx_payload)
            if not _verify_ed25519_signature(public_key, msg_bytes, signature):
                return "ERR02|Invalid signature"

            self.logger.info(f" Processing asset send: {sender_username} -> {receiver_username} (asset: {asset_id})")

            transfer = {
                'tx_id': tx_id,
                'tx_type': 'transfer',
                'from': sender_username,
                'to': receiver_username,
                'asset_id': asset_id,
                'asset_hash': asset_hash,
                'asset_name': item.get('asset_name'),
                'amount': 0,
                'timestamp': timestamp,
                'public_key': public_key,
                'signature': signature,
            }

            with self.server.tx_status_lock:
                if tx_id in self.server.tx_status:
                    return "ERR02|Duplicate tx_id"
                self.server.tx_status[tx_id] = {
                    'status': 'queued',
                    'message': 'Queued for PoW transfer',
                    'created_at': time.time(),
                    'asset_id': asset_id,
                    'asset_name': item.get('asset_name'),
                    'tx_type': 'transfer',
                    'sender': sender_username,
                    'receiver': receiver_username,
                }
            self.server.tx_queue.put(transfer)

            self.logger.info(f" Asset transfer queued for PoW: {tx_id}")
            return f"OK|PENDING|{tx_id}"
            
        except Exception as e:
            self.logger.error(f" Error processing SEND: {e}")
            return f"ERR99|{str(e)}"

    def handle_get_profile(self, params):
        """
        GET_PROFILE - Get user profile (anonymous)
        Format: GET_PROFILE|username
        Returns: OK|username|email|created_at or ERR|error_message
        """
        if len(params) < 1:
            self.logger.error("[RECV] GET_PROFILE - Invalid format")
            return "ERR01|Invalid format: GET_PROFILE|username"
        try:
            username = params[0].strip()
            if not username or '|' in username:
                self.logger.error(" Invalid username format")
                return "ERR01|Invalid username"
            user_obj = self.db.get_user(username)
            if not user_obj:
                self.logger.error(f" User {username} not found")
                return "ERR02|User not found"
            self.logger.info(f" Profile retrieved for {username}")
            return f"OK|{username}|{user_obj.email}|{user_obj.created_at}"
        except Exception as e:
            self.logger.error(f" Error processing GET_PROFILE: {e}")
            return f"ERR99|{str(e)}"

    def handle_get_tx_status(self, params):
        """
        GET_TX_STATUS - Check transaction status
        Format: GET_TX_STATUS|tx_id
        Returns: OK|STATUS|message or ERR|error_message
        """
        if len(params) < 1:
            return "ERR01|Invalid format: GET_TX_STATUS|tx_id"
        tx_id = params[0].strip()
        if not tx_id:
            return "ERR01|Invalid tx_id"

        info = self.server._get_tx_info(tx_id)
        if not info:
            return "ERR02|Transaction not found"

        status = info.get('status', 'unknown')
        message = info.get('message', '')
        created_at = info.get('created_at', time.time())

        if status in ('queued', 'submitted'):
            if time.time() - created_at > self.server.tx_timeout_seconds:
                status = 'timeout'
                message = 'PoW Timeout after 10 mins'
                self.server._set_tx_status(tx_id, status, message)

        return f"OK|{status.upper()}|{message}"

    def handle_get_items_by_user(self, params):
        """
        GET_ITEMS_BY_USER - Get assets owned by a user
        Format: GET_ITEMS_BY_USER|username
        Returns: OK|items_json or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: GET_ITEMS_BY_USER|username"
        username = params[0].strip()
        if not username or '|' in username:
            return "ERR01|Invalid username"
        if username != self.username:
            return "ERR02|Unauthorized"
        try:
            items = self.db.get_items_by_username(username)
            return f"OK|{json.dumps(items)}"
        except Exception as e:
            return f"ERR03|Error getting items: {str(e)}"

    def handle_get_wallet(self, params):
        """
        GET_WALLET - Get wallet balance for a user
        Format: GET_WALLET|username
        Returns: OK|balance|updated_at or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: GET_WALLET|username"

        username = params[0].strip()
        if not username or '|' in username:
            return "ERR01|Invalid username"
        if username != self.username:
            return "ERR02|Unauthorized"

        try:
            self.db.ensure_wallet(username, 100)
            wallet = self.db.get_wallet(username)
            if not wallet:
                return "ERR02|Wallet not found"
            balance = wallet.get('balance', 0)
            updated_at = wallet.get('updated_at') or ''
            return f"OK|{balance}|{updated_at}"
        except Exception as e:
            return f"ERR03|Error getting wallet: {str(e)}"

    def handle_get_notifications(self, params):
        """
        GET_NOTIFICATIONS - Get notifications for a user
        Format: GET_NOTIFICATIONS|username|limit
        Returns: OK|json_list|unread_count or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: GET_NOTIFICATIONS|username|limit"
        username = params[0].strip()
        if not username or '|' in username:
            return "ERR01|Invalid username"
        if username != self.username:
            return "ERR02|Unauthorized"
        limit = 20
        if len(params) >= 2:
            try:
                limit = int(params[1])
            except Exception:
                limit = 20
        try:
            items = self.db.get_notifications(username, limit=limit)
            unread_count = self.db.get_unread_notifications_count(username)
            payload = items or []
            return f"OK|{json.dumps(payload)}|{unread_count}"
        except Exception as e:
            return f"ERR03|Error getting notifications: {str(e)}"

    def handle_mark_notifications_read(self, params):
        """
        MARK_NOTIFICATIONS_READ - Mark all notifications as read for a user
        Format: MARK_NOTIFICATIONS_READ|username
        Returns: OK|read or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 1:
            return "ERR01|Invalid format: MARK_NOTIFICATIONS_READ|username"
        username = params[0].strip()
        if not username or '|' in username:
            return "ERR01|Invalid username"
        if username != self.username:
            return "ERR02|Unauthorized"
        try:
            ok = self.db.mark_all_notifications_read(username)
            return "OK|read" if ok else "ERR03|Failed to mark notifications read"
        except Exception as e:
            return f"ERR03|Error marking notifications: {str(e)}"

    def handle_register_device(self, params):
        """
        REGISTER_DEVICE - Register push notification token
        Format: REGISTER_DEVICE|username|platform|token
        Returns: OK|registered or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 3:
            return "ERR01|Invalid format: REGISTER_DEVICE|username|platform|token"

        username = params[0].strip()
        platform = params[1].strip().lower()
        token = params[2].strip()

        if not username or not token or '|' in username or '|' in token:
            return "ERR01|Invalid parameters"
        if username != self.username:
            return "ERR02|Unauthorized"

        if len(token) < 10:
            return "ERR01|Invalid token"
        if platform not in ("android", "ios", "web"):
            platform = "unknown"

        ok = self.db.upsert_device_token(username, token, platform)
        if not ok:
            return "ERR03|Failed to register device"
        return "OK|registered"

    def handle_update_public_key(self, params):
        """
        UPDATE_PUBLIC_KEY - Replace stored public key after client key regeneration.
        Format: UPDATE_PUBLIC_KEY|username|new_public_key_b64
        Returns: OK|updated or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 2:
            return "ERR01|Invalid format: UPDATE_PUBLIC_KEY|username|public_key_b64"
        username = params[0].strip()
        new_pk = params[1].strip()
        if not username or not new_pk or '|' in username:
            return "ERR01|Invalid parameters"
        if username != self.username:
            return "ERR02|Unauthorized"
        try:
            ok = self.db.set_user_public_key_force(username, new_pk)
            if ok:
                self.logger.info(f" Public key updated for {username}")
                return "OK|updated"
            return "ERR03|Failed to update public key"
        except Exception as e:
            return f"ERR99|{str(e)}"

    def handle_list_item(self, params):
        """
        LIST_ITEM - List an owned asset for sale
        Format: LIST_ITEM|asset_id|username|price
        Returns: OK|LISTED or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 3:
            return "ERR01|Invalid format: LIST_ITEM|asset_id|username|price"

        asset_id = params[0].strip()
        username = params[1].strip()
        price_str = params[2].strip()

        if not asset_id or not username or '|' in username:
            return "ERR01|Invalid parameters"
        if username != self.username:
            return "ERR02|Unauthorized"

        try:
            price = float(price_str)
        except Exception:
            return "ERR01|Invalid price format"
        if price <= 0:
            return "ERR01|Price must be positive"

        item = self.db.get_item_by_id(asset_id)
        if not item:
            return "ERR02|Asset not found"
        if item.get('username') != username:
            return "ERR02|Unauthorized"

        updated = self.db.update_item_listing(asset_id, True, new_cost=price)
        if updated:
            return "OK|LISTED"
        return "ERR03|Failed to list item"

    def handle_unlist_item(self, params):
        """
        UNLIST_ITEM - Remove an asset from marketplace listing
        Format: UNLIST_ITEM|asset_id|username
        Returns: OK|UNLISTED or ERR|error_message
        """
        if not self.is_authenticated:
            return "ERR02|Not authenticated"
        if len(params) < 2:
            return "ERR01|Invalid format: UNLIST_ITEM|asset_id|username"

        asset_id = params[0].strip()
        username = params[1].strip()

        if not asset_id or not username or '|' in username:
            return "ERR01|Invalid parameters"
        if username != self.username:
            return "ERR02|Unauthorized"

        item = self.db.get_item_by_id(asset_id)
        if not item:
            return "ERR02|Asset not found"
        if item.get('username') != username:
            return "ERR02|Unauthorized"

        updated = self.db.update_item_listing(asset_id, False)
        if updated:
            self.server.broadcast_marketplace_remove(asset_id)
            return "OK|UNLISTED"
        return "ERR03|Failed to unlist item"


class Server:
    """Main server that handles all client connections"""
    
    def __init__(self, host=SERVER_HOST, port=SERVER_PORT):
        self.host = host
        self.port = port
        self.server_ip = _resolve_server_ip(SERVER_IP, host)  # Broadcast response IP
        self.logger = AurexLogger.get_logger(__name__)
        
        self.clients_lock = threading.Lock()
        self.clients = {}  # addr -> ClientSession
        self.clients_by_username = {}  # username -> set(ClientSession)
        self.is_running = False
        self.db = MarketplaceDB()
        self.notifications_manager = NotificationsManager()
        self.upload_sessions = {}
        self.upload_sessions_lock = threading.Lock()

        # Purchase -> gateway queue + status tracking
        self.tx_queue = queue.Queue()
        self.tx_status = {}
        self.tx_status_lock = threading.Lock()
        self.tx_timeout_seconds = 600  # 10 minutes
        self.confirmed_tx_ids = set()

        # Start background worker for gateway submissions
        worker = threading.Thread(target=self._tx_worker, daemon=True)
        worker.start()
        # Start timeout monitor for queued/submitted purchases
        timeout_worker = threading.Thread(target=self._tx_timeout_worker, daemon=True)
        timeout_worker.start()

    def register_authenticated_session(self, session):
        """Track authenticated sessions for notifications/broadcasts."""
        if not session or not session.username:
            return
        with self.clients_lock:
            sessions = self.clients_by_username.setdefault(session.username, set())
            sessions.add(session)

    def unregister_session(self, session, username=None):
        """Remove session from tracking structures."""
        if not session and not username:
            return
        uname = username or getattr(session, 'username', None)
        with self.clients_lock:
            if uname and uname in self.clients_by_username:
                try:
                    self.clients_by_username[uname].discard(session)
                    if not self.clients_by_username[uname]:
                        del self.clients_by_username[uname]
                except Exception:
                    pass

    def _send_event(self, session, event_payload):
        """Send an async event to a single session."""
        if not session:
            return
        try:
            raw = serialize_event(event_payload).encode()
            session.proto.send_one_message(raw)
        except Exception as e:
            server_logger.warning("event send failed: %s", e)

    def send_event_to_user(self, username, event_payload):
        """Send an async event to all active sessions for a user."""
        if not username:
            return
        with self.clients_lock:
            sessions = list(self.clients_by_username.get(username, set()))
        for session in sessions:
            self._send_event(session, event_payload)

    def broadcast_event(self, event_payload):
        """Broadcast an async event to all connected sessions."""
        with self.clients_lock:
            sessions = list(self.clients.values())
        for session in sessions:
            self._send_event(session, event_payload)

    def broadcast_marketplace_remove(self, asset_id):
        payload = {
            'event': 'marketplace_remove',
            'payload': {'asset_id': str(asset_id)},
        }
        self.broadcast_event(payload)

    def create_and_push_notification(self, username, title, body, notif_type="system", asset_id=None, tx_id=None):
        notif = self.db.create_notification(
            username=username,
            title=title,
            body=body,
            notif_type=notif_type,
            asset_id=asset_id,
            tx_id=tx_id,
        )
        if not notif and self.notifications_manager:
            notif = self.notifications_manager.create_notification(
                username=username,
                title=title,
                body=body,
                notif_type=notif_type,
                asset_id=asset_id,
                tx_id=tx_id,
            )
        if notif:
            payload_notif = notif.to_dict() if hasattr(notif, "to_dict") else notif
            payload = {
                'event': 'notification',
                'payload': payload_notif,
            }
            self.send_event_to_user(username, payload)
            if FCM_ENABLED and FCM_SERVER_KEY:
                threading.Thread(
                    target=self._send_push_notification,
                    args=(username, title, body, notif_type, asset_id, tx_id),
                    daemon=True,
                ).start()
        return notif

    def _send_push_notification(self, username, title, body, notif_type, asset_id=None, tx_id=None):
        """Send push notification via FCM to all devices for a user."""
        try:
            tokens = self.db.get_device_tokens(username)
            if not tokens:
                return
            payload = {
                "registration_ids": tokens,
                "priority": "high",
                "notification": {
                    "title": title,
                    "body": body,
                },
                "data": {
                    "type": notif_type or "system",
                    "title": title,
                    "body": body,
                    "asset_id": asset_id or "",
                    "tx_id": tx_id or "",
                },
            }
            resp = self._post_fcm(payload)
            if not resp or not isinstance(resp, dict):
                return
            results = resp.get("results") or []
            invalid = []
            for token, result in zip(tokens, results):
                error = result.get("error")
                if error in ("NotRegistered", "InvalidRegistration", "MismatchSenderId"):
                    invalid.append(token)
            for token in invalid:
                self.db.delete_device_token(token)
        except Exception as e:
            server_logger.warning("push send failed: %s", e)

    def _post_fcm(self, payload):
        """Send raw payload to FCM legacy HTTP API."""
        if not FCM_SERVER_KEY:
            return None
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                "https://fcm.googleapis.com/fcm/send",
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"key={FCM_SERVER_KEY}",
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8")
            if not body:
                return {}
            return json.loads(body)
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
                server_logger.warning("FCM HTTP error %s: %s", e.code, err_body)
            except Exception:
                server_logger.warning("FCM HTTP error %s", e.code)
            return None
        except Exception as e:
            server_logger.warning("FCM send error: %s", e)
            return None

    def _emit_tx_notifications(self, tx_id, info):
        tx_type = info.get('tx_type', 'purchase')
        status = info.get('status')
        asset_id = info.get('asset_id')
        asset_name = info.get('asset_name') or (f"asset {asset_id}" if asset_id else "asset")
        message = info.get('message') or ''

        if tx_type == 'mint':
            owner = info.get('owner')
            if status == 'confirmed':
                if owner:
                    self.create_and_push_notification(
                        username=owner,
                        title="Asset authenticated on blockchain",
                        body=f'"{asset_name}" has been confirmed on the blockchain. It is now live on the marketplace.',
                        notif_type="mint_confirmed",
                        asset_id=asset_id,
                        tx_id=tx_id,
                    )
            elif status in ('failed', 'timeout'):
                if owner:
                    detail = message if message else f'Blockchain authentication of "{asset_name}" failed.'
                    self.create_and_push_notification(
                        username=owner,
                        title="Asset authentication failed",
                        body=detail,
                        notif_type="mint_failed",
                        asset_id=asset_id,
                        tx_id=tx_id,
                    )
            return

        if tx_type == 'transfer':
            sender = info.get('sender')
            receiver = info.get('receiver')
            if status == 'confirmed':
                if receiver:
                    self.create_and_push_notification(
                        username=receiver,
                        title="Asset received",
                        body=f"You received {asset_name} from {sender or 'another user'}.",
                        notif_type="asset_received",
                        asset_id=asset_id,
                        tx_id=tx_id,
                    )
                if sender:
                    self.create_and_push_notification(
                        username=sender,
                        title="Asset sent",
                        body=f"Your asset {asset_name} was sent to {receiver or 'another user'}.",
                        notif_type="asset_sent",
                        asset_id=asset_id,
                        tx_id=tx_id,
                    )
            elif status in ('failed', 'timeout'):
                if sender:
                    detail = message if message else f"Your transfer of {asset_name} failed."
                    self.create_and_push_notification(
                        username=sender,
                        title="Transfer failed",
                        body=detail,
                        notif_type="asset_transfer_failed",
                        asset_id=asset_id,
                        tx_id=tx_id,
                    )
            return

        buyer = info.get('buyer')
        seller = info.get('seller')
        if status == 'confirmed':
            if asset_id:
                self.db.set_item_listed(asset_id, False)
                self.broadcast_marketplace_remove(asset_id)
            if buyer:
                self.create_and_push_notification(
                    username=buyer,
                    title="Purchase confirmed",
                    body=f"Your purchase of {asset_name} is confirmed.",
                    notif_type="purchase_confirmed",
                    asset_id=asset_id,
                    tx_id=tx_id,
                )
            if seller:
                self.create_and_push_notification(
                    username=seller,
                    title="Asset sold",
                    body=f"{buyer} bought your asset {asset_name}.",
                    notif_type="asset_sold",
                    asset_id=asset_id,
                    tx_id=tx_id,
                )
        elif status in ('failed', 'timeout'):
            if buyer:
                detail = message if message else f"Your purchase of {asset_name} failed."
                self.create_and_push_notification(
                    username=buyer,
                    title="Purchase failed",
                    body=detail,
                    notif_type="purchase_failed",
                    asset_id=asset_id,
                    tx_id=tx_id,
                )
    def _start_broadcast_listener(self):
        """Start listening for WHRSRV (Where's Server) broadcast queries"""
        def broadcast_loop():
            try:
                # Create UDP socket for broadcast listening
                broadcast_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                broadcast_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                broadcast_sock.settimeout(1.0)  # 1 second timeout to allow checking is_running
                broadcast_sock.bind(('0.0.0.0', BROADCAST_PORT))
                
                self.logger.info(f" Broadcast listener started on port {BROADCAST_PORT}")
                
                while self.is_running:
                    try:
                        data, addr = broadcast_sock.recvfrom(1024)
                        message = data.decode("utf-8").strip()

                        if DiscoveryRequest.matches(message):
                            response = DiscoveryResponse(host=self.server_ip, port=self.port).to_text()
                            broadcast_sock.sendto(response.encode("utf-8"), addr)
                            self.logger.debug(f" Broadcast response sent to {addr}: {response}")
                    except socket.timeout:
                        continue
                    except Exception as e:
                        self.logger.debug(f" Broadcast listener error: {e}")
                
                broadcast_sock.close()
            except Exception as e:
                self.logger.debug(f" Failed to start broadcast listener: {e}")
        
        # Start broadcast listener in a separate thread
        thread = threading.Thread(target=broadcast_loop, daemon=True)
        thread.start()

    def _start_block_confirmation_listener(self):
        """Background listener: receive block_confirmation from RPC server (blockchain)."""
        def listen_loop():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('0.0.0.0', BLOCK_CONFIRMATION_PORT))
                sock.listen(5)
                sock.settimeout(1.0)
                self.logger.info(" Block confirmation listener on port %s" % BLOCK_CONFIRMATION_PORT)
                while self.is_running:
                    try:
                        client, addr = sock.accept()
                        client.settimeout(5)
                        raw_buf = b''
                        while b'\n' not in raw_buf and len(raw_buf) < 65536:
                            chunk = client.recv(4096)
                            if not chunk:
                                break
                            raw_buf += chunk
                        client.close()
                        if raw_buf:
                            line = raw_buf.decode('utf-8', errors='ignore').strip()
                            if line:
                                msg = json.loads(line)
                                if msg.get('type') == 'block_confirmation':
                                    server_logger.info(
                                        "block_confirmation block_index=%s block_hash=%s miner_id=%s",
                                        msg.get('block_index'), msg.get('block_hash', '')[:16], msg.get('miner_id')
                                    )
                                    self.logger.info(
                                        " Block confirmed: index=%s hash=%s...",
                                        msg.get('block_index'),
                                        (msg.get('block_hash') or '')[:16],
                                    )
                                    for tx in msg.get('transactions', []):
                                        tx_data = tx.get('data') if isinstance(tx.get('data'), dict) else {}
                                        action = tx_data.get('action')
                                        from_user = tx_data.get('from') or tx.get('sender')
                                        to_user = tx_data.get('to')
                                        amount = tx_data.get('amount') if tx_data.get('amount') is not None else tx_data.get('price')
                                        asset_id = tx_data.get('asset_id')
                                        asset_hash = tx_data.get('asset_hash')
                                        tx_id = tx_data.get('tx_id')
                                        if tx_id and tx_id in self.confirmed_tx_ids:
                                            continue

                                        if action == 'asset_mint':
                                            cost = tx_data.get('cost')
                                            if cost is None:
                                                cost = tx_data.get('amount') if tx_data.get('amount') is not None else tx_data.get('price')
                                            # Move asset from pending -> marketplace FIRST
                                            approved_id = None
                                            mint_ok = False
                                            if asset_hash:
                                                ok, approve_msg, new_id = self.db.approve_pending_asset_by_hash(asset_hash)
                                                if ok:
                                                    approved_id = new_id
                                                    mint_ok = True
                                                    server_logger.info(
                                                        "mint: approved pending asset hash=%s new_marketplace_id=%s",
                                                        asset_hash[:16], new_id,
                                                    )
                                                else:
                                                    server_logger.warning(
                                                        "mint: pending asset not found hash=%s (%s)",
                                                        asset_hash[:16] if asset_hash else '?', approve_msg,
                                                    )
                                            else:
                                                server_logger.warning("mint: block_confirmation missing asset_hash")
                                            if not mint_ok:
                                                existing = self.db.get_item_by_hash(asset_hash) if asset_hash else None
                                                if existing:
                                                    mint_ok = True
                                                    approved_id = existing.get('id')
                                                else:
                                                    if tx_id:
                                                        self._set_tx_status(tx_id, "failed", "Pending asset not found for mint hash")
                                                    continue
                                            # Store the approved marketplace asset_id in tx_status
                                            if tx_id and approved_id is not None:
                                                with self.tx_status_lock:
                                                    info = self.tx_status.get(tx_id)
                                                    if info is not None:
                                                        info['asset_id'] = str(approved_id)
                                            if tx_id:
                                                self._set_tx_status(tx_id, "confirmed", "Mint confirmed")
                                                self.confirmed_tx_ids.add(tx_id)
                                            continue

                                        if action in ('asset_purchase', 'purchase'):
                                            buyer = from_user
                                            seller = to_user
                                            buyer_public_key = tx.get('public_key', '') if isinstance(tx, dict) else ''
                                            try:
                                                amt = float(amount) if amount is not None else None
                                            except (ValueError, TypeError):
                                                amt = None
                                            if not buyer or not seller or amt is None:
                                                if tx_id:
                                                    self._set_tx_status(tx_id, "failed", "Invalid purchase payload")
                                                continue
                                            if action == 'asset_purchase':
                                                gw_status = str(tx.get('gateway_status', '')).lower() if isinstance(tx, dict) else ''
                                                gw_message = tx.get('gateway_message') if isinstance(tx, dict) else None
                                                if gw_status == 'failed':
                                                    if tx_id:
                                                        self._set_tx_status(
                                                            tx_id,
                                                            "failed",
                                                            str(gw_message or "Gateway finalization failed"),
                                                        )
                                                        self.confirmed_tx_ids.add(tx_id)
                                                    continue

                                                item = None
                                                if asset_id:
                                                    item = self.db.get_item_by_id(str(asset_id))
                                                if not item and asset_hash:
                                                    item = self.db.get_item_by_hash(asset_hash)

                                                already_finalized = bool(
                                                    item
                                                    and (item.get('username') or '') == buyer
                                                    and int(item.get('is_listed') or 0) == 0
                                                )

                                                if already_finalized and buyer_public_key:
                                                    if asset_id:
                                                        self.db.update_asset_owner(
                                                            str(asset_id),
                                                            buyer,
                                                            buyer_public_key,
                                                        )
                                                    elif asset_hash:
                                                        self.db.update_asset_owner_by_hash(
                                                            asset_hash,
                                                            buyer,
                                                            buyer_public_key,
                                                        )

                                                if not already_finalized:
                                                    ok, res = self.db.transfer(buyer, seller, amt)
                                                    if not ok:
                                                        server_logger.warning("purchase finalize transfer failed: %s", res)
                                                        if tx_id:
                                                            self._set_tx_status(tx_id, "failed", res)
                                                            self.confirmed_tx_ids.add(tx_id)
                                                        continue

                                                    updated = False
                                                    if asset_id:
                                                        updated = self.db.update_asset_owner(
                                                            str(asset_id),
                                                            buyer,
                                                            buyer_public_key or None,
                                                        )
                                                    if not updated and asset_hash:
                                                        updated = self.db.update_asset_owner_by_hash(
                                                            asset_hash,
                                                            buyer,
                                                            buyer_public_key or None,
                                                        )
                                                    if asset_id:
                                                        self.db.set_item_listed(str(asset_id), False)
                                                        self.broadcast_marketplace_remove(str(asset_id))
                                                    elif asset_hash:
                                                        self.db.set_item_listed_by_hash(asset_hash, False)
                                                        resolved = self.db.get_item_by_hash(asset_hash)
                                                        if resolved and resolved.get('id'):
                                                            self.broadcast_marketplace_remove(str(resolved['id']))

                                                    if not updated:
                                                        if tx_id:
                                                            self._set_tx_status(tx_id, "failed", "Asset ownership update failed")
                                                            self.confirmed_tx_ids.add(tx_id)
                                                        continue

                                                if tx_id:
                                                    self._set_tx_status(tx_id, "confirmed", "Transaction confirmed")
                                                    self.confirmed_tx_ids.add(tx_id)
                                                continue

                                            # Legacy fallback: pre-upgrade "purchase" blocks are finalized here.
                                            ok, res = self.db.transfer(buyer, seller, amt)
                                            if ok:
                                                new_owner = buyer
                                                updated = False
                                                if asset_id:
                                                    updated = self.db.update_asset_owner(str(asset_id), new_owner, buyer_public_key or None)
                                                if not updated and asset_hash:
                                                    updated = self.db.update_asset_owner_by_hash(asset_hash, new_owner, buyer_public_key or None)
                                                if asset_id:
                                                    self.db.set_item_listed(str(asset_id), False)
                                                    self.broadcast_marketplace_remove(str(asset_id))
                                                if updated:
                                                    server_logger.info(
                                                        "purchase (legacy): asset_id=%s transferred to buyer=%s", asset_id, new_owner
                                                    )
                                                    if tx_id:
                                                        self._set_tx_status(tx_id, "confirmed", "Transaction confirmed")
                                                else:
                                                    server_logger.warning(
                                                        "purchase (legacy): ownership update failed asset_id=%s", asset_id
                                                    )
                                                    if tx_id:
                                                        self._set_tx_status(tx_id, "failed", "Asset ownership update failed")
                                            else:
                                                server_logger.warning("purchase (legacy): wallet transfer failed: %s", res)
                                                if tx_id:
                                                    self._set_tx_status(tx_id, "failed", res)
                                            continue

                                        if action == 'asset_transfer':
                                            if from_user and to_user and (asset_id or asset_hash):
                                                updated = False
                                                if asset_hash:
                                                    updated = self.db.update_asset_owner_by_hash(asset_hash, to_user)
                                                if not updated and asset_id:
                                                    updated = self.db.update_asset_owner(str(asset_id), to_user)
                                                if updated:
                                                    if asset_id:
                                                        self.db.set_item_listed(str(asset_id), False)
                                                        self.broadcast_marketplace_remove(str(asset_id))
                                                    server_logger.info(
                                                        "asset transfer updated: asset_id=%s new_owner=%s", asset_id, to_user
                                                    )
                                                else:
                                                    server_logger.warning(
                                                        "asset transfer update failed: asset_id=%s", asset_id
                                                    )
                                                if tx_id:
                                                    self._set_tx_status(tx_id, "confirmed", "Transfer confirmed")
                                            else:
                                                if tx_id:
                                                    self._set_tx_status(tx_id, "failed", "Invalid transfer payload")
                                            continue

                                        # Generic fallback: plain wallet transfer
                                        if from_user and to_user is not None and amount is not None:
                                            try:
                                                amt_val = float(amount)
                                                ok, res = self.db.transfer(from_user, to_user, amt_val)
                                                if ok:
                                                    server_logger.info("wallet transfer: %s -> %s amount=%s: %s", from_user, to_user, amt_val, res)
                                                    self.logger.info(" Saved: %s" % res)
                                                    wa, wb = self.db.get_wallet(from_user), self.db.get_wallet(to_user)
                                                    if wa and wb:
                                                        server_logger.info("balances: %s=%.2f %s=%.2f", from_user, wa['balance'], to_user, wb['balance'])
                                                    if asset_id or asset_hash:
                                                        updated = False
                                                        if asset_id:
                                                            updated = self.db.update_asset_owner(str(asset_id), to_user)
                                                        if not updated and asset_hash:
                                                            updated = self.db.update_asset_owner_by_hash(asset_hash, to_user)
                                                        if updated:
                                                            server_logger.info("asset ownership updated: asset_id=%s owner=%s", asset_id, to_user)
                                                        else:
                                                            server_logger.warning("asset ownership update failed: asset_id=%s", asset_id)
                                                    if tx_id:
                                                        self._set_tx_status(tx_id, "confirmed", "Transaction confirmed")
                                                else:
                                                    server_logger.warning("wallet transfer failed: %s", res)
                                                    if tx_id:
                                                        self._set_tx_status(tx_id, "failed", res)
                                            except (ValueError, TypeError) as e:
                                                server_logger.warning("skip tx (bad amount): %s", e)
                    except socket.timeout:
                        continue
                    except json.JSONDecodeError as e:
                        server_logger.warning("block_confirmation parse error: %s", e)
                    except Exception as e:
                        if self.is_running:
                            server_logger.warning("block_confirmation listener: %s", e)
                sock.close()
            except Exception as e:
                server_logger.error("block_confirmation listener failed: %s", e)
        thread = threading.Thread(target=listen_loop, daemon=True)
        thread.start()

    def _set_tx_status(self, tx_id, status, message=None):
        emit_info = None
        with self.tx_status_lock:
            info = self.tx_status.get(tx_id)
            if not info:
                self.tx_status[tx_id] = {
                    'status': status,
                    'message': message or '',
                    'created_at': time.time(),
                }
                info = self.tx_status[tx_id]
            else:
                info['status'] = status
                if message is not None:
                    info['message'] = message
            if status in ('confirmed', 'failed', 'timeout') and not info.get('notified'):
                info['notified'] = True
                emit_info = dict(info)
        if status in ('failed', 'timeout') and emit_info and emit_info.get('tx_type') == 'mint':
            self._cleanup_failed_mint(emit_info)
        if emit_info:
            self._emit_tx_notifications(tx_id, emit_info)

    def _cleanup_failed_mint(self, info):
        """Remove unconfirmed mint assets from pending table + storage."""
        asset_id = info.get('asset_id')
        asset_hash = info.get('asset_hash')
        metadata_link = info.get('metadata_link') or ''
        deleted = False
        if asset_hash:
            deleted = self.db.delete_pending_asset_by_hash(asset_hash)
        if deleted:
            self.logger.warning(f" Mint failed; removed pending asset {asset_id or asset_hash}")
        if metadata_link:
            try:
                path = _resolve_upload_file(metadata_link)
                if path and path.exists():
                    path.unlink()
            except Exception as e:
                server_logger.warning("mint cleanup: failed to remove asset file: %s", e)

    def _get_tx_info(self, tx_id):
        with self.tx_status_lock:
            info = self.tx_status.get(tx_id)
            return dict(info) if info else None

    def _tx_timeout_worker(self):
        while True:
            time.sleep(5)
            now = time.time()
            to_timeout = []
            with self.tx_status_lock:
                for tx_id, info in list(self.tx_status.items()):
                    status = info.get('status')
                    created_at = info.get('created_at', now)
                    if status in ('queued', 'submitted') and now - created_at > self.tx_timeout_seconds:
                        to_timeout.append(tx_id)
            for tx_id in to_timeout:
                self._set_tx_status(tx_id, 'timeout', 'PoW Timeout after 10 mins')

    def _tx_worker(self):
        while True:
            tx_job = self.tx_queue.get()
            if not tx_job:
                self.tx_queue.task_done()
                continue
            tx_id = tx_job.get('tx_id')
            tx_type = tx_job.get('tx_type', 'purchase')
            try:
                if tx_type == 'transfer':
                    response = self._submit_transfer_to_gateway(tx_job)
                elif tx_type == 'mint':
                    response = self._submit_mint_to_gateway(tx_job)
                else:
                    response = self._submit_purchase_to_gateway(tx_job)
                if response and response.get('status') == 'submitted':
                    self._set_tx_status(tx_id, "submitted", response.get('message', 'Submitted to gateway'))
                    if tx_type == 'mint':
                        owner = tx_job.get('owner')
                        asset_name = tx_job.get('asset_name') or 'asset'
                        asset_id = tx_job.get('asset_id')
                        if owner:
                            self.create_and_push_notification(
                                username=owner,
                                title="Asset uploaded",
                                body=f"Your asset {asset_name} has been uploaded.",
                                notif_type="asset_uploaded",
                                asset_id=asset_id,
                                tx_id=tx_id,
                            )
                else:
                    msg = response.get('message') if response else "Gateway did not respond"
                    self._set_tx_status(tx_id, "failed", msg)
            except Exception as e:
                self._set_tx_status(tx_id, "failed", f"Gateway error: {e}")
            finally:
                self.tx_queue.task_done()

    def _submit_purchase_to_gateway(self, purchase):
        payload = {
            'action': '/buy',
            'body': {
                'tx_id': purchase.get('tx_id'),
                'buyer': purchase.get('buyer'),
                'seller': purchase.get('seller'),
                'asset_id': purchase.get('asset_id'),
                'asset_hash': purchase.get('asset_hash'),
                'asset_name': purchase.get('asset_name'),
                'buyer_pub': purchase.get('public_key'),
                'price': purchase.get('amount'),
                'timestamp': purchase.get('timestamp'),
                'public_key': purchase.get('public_key'),
                'signature': purchase.get('signature'),
            }
        }
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((GATEWAY_HOST, GATEWAY_PORT))
        raw = json.dumps(payload).encode()
        sock.send(struct.pack('>H', len(raw)) + raw)
        response = self._recv_gateway_json(sock)
        sock.close()
        return response

    def _submit_transfer_to_gateway(self, transfer):
        tx_payload = {
            'action': 'asset_transfer',
            'tx_id': transfer.get('tx_id'),
            'asset_id': transfer.get('asset_id'),
            'asset_hash': transfer.get('asset_hash'),
            'asset_name': transfer.get('asset_name'),
            'from': transfer.get('from'),
            'to': transfer.get('to'),
            'amount': transfer.get('amount', 0),
            'timestamp': transfer.get('timestamp'),
        }
        payload = {
            'action': 'submit_transaction',
            'body': {
                'sender': transfer.get('from'),
                'data': tx_payload,
                'signature': transfer.get('signature'),
                'public_key': transfer.get('public_key'),
            }
        }
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((GATEWAY_HOST, GATEWAY_PORT))
        raw = json.dumps(payload).encode()
        sock.send(struct.pack('>H', len(raw)) + raw)
        response = self._recv_gateway_json(sock)
        sock.close()
        return response

    def _submit_mint_to_gateway(self, mint):
        tx_payload = {
            'action': 'asset_mint',
            'tx_id': mint.get('tx_id'),
            'asset_hash': mint.get('asset_hash'),
            'asset_name': mint.get('asset_name'),
            'file_name': mint.get('file_name'),
            'owner': mint.get('owner'),
            'owner_pub': mint.get('public_key'),
            'cost': mint.get('cost'),
            'timestamp': mint.get('timestamp'),
        }
        payload = {
            'action': 'submit_transaction',
            'body': {
                'sender': mint.get('owner'),
                'data': tx_payload,
                'signature': mint.get('signature'),
                'public_key': mint.get('public_key'),
            }
        }
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((GATEWAY_HOST, GATEWAY_PORT))
        raw = json.dumps(payload).encode()
        sock.send(struct.pack('>H', len(raw)) + raw)
        response = self._recv_gateway_json(sock)
        sock.close()
        return response

    def _recv_gateway_json(self, sock, max_size=65536):
        len_buf = sock.recv(2)
        if len(len_buf) < 2:
            return None
        size = struct.unpack('>H', len_buf)[0]
        if size > max_size:
            return None
        data = b''
        while len(data) < size:
            chunk = sock.recv(min(size - len(data), 4096))
            if not chunk:
                return None
            data += chunk
        try:
            return json.loads(data.decode())
        except Exception:
            return None
    
    def start(self):
        """Start the WSS server."""
        self.logger.info(f" Server starting on {self.host}:{self.port}...")
        try:
            asyncio.run(self._run_server_async())
        except KeyboardInterrupt:
            self.logger.info(" Server shutting down...")
        except Exception as e:
            self.logger.error(f" Critical server error: {e}")
        finally:
            self.is_running = False
            self.logger.info(" Server shutdown complete")

    async def _run_server_async(self):
        self.is_running = True
        if ENABLE_UDP_DISCOVERY:
            self._start_broadcast_listener()
        self._start_block_confirmation_listener()

        context = ssl_module.SSLContext(ssl_module.PROTOCOL_TLS_SERVER)
        cert_path = _resolve_path(SSL_CERT_FILE)
        key_path = _resolve_path(SSL_KEY_FILE)
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)

        async with websockets.serve(
            self.handle_client,
            self.host,
            self.port,
            ssl=context,
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
        ):
            self.logger.info(f" Server listening on wss://{self.server_ip}:{self.port}")
            await asyncio.Future()

    async def _handle_upload_chunk_message(self, session, addr, message):
        if not (isinstance(message, bytes) and message.startswith(UPLOAD_CHUNK_PREFIX)):
            return False

        response = "ERR|INVALID_ID"
        try:
            parts = message.split(b"|", 2)
            if len(parts) == 3 and len(parts[2]) >= 4:
                upload_id = parts[1].decode("ascii").strip()
                if upload_id and upload_id != "[]":
                    sequence = struct.unpack("!I", parts[2][:4])[0]
                    chunk_data = parts[2][4:]
                    response = await asyncio.to_thread(
                        session._handle_binary_chunk_inline,
                        upload_id,
                        sequence,
                        chunk_data,
                    )
        except Exception as chunk_err:
            self.logger.error(f" Malformed binary chunk from {addr[0]}:{addr[1]}: {chunk_err}")

        self.logger.debug(f" {addr[0]}:{addr[1]} -> {response[:80]}")
        await session.proto.async_send_one_message(response.encode())
        return True

    async def _handle_asset_binary_message(self, session, addr, message):
        if not (isinstance(message, bytes) and message.startswith(GET_ASSET_BINARY_PREFIX)):
            return False

        rel_path = message.split(b"|", 1)[1].decode("utf-8").strip()
        self.logger.info(
            f" {addr[0]}:{addr[1]} <- "
            f"{serialize_command(ProtocolCommand.GET_ASSET_BINARY, rel_path)}"
        )
        self.logger.debug(f" Processing command: {ProtocolCommand.GET_ASSET_BINARY.value}")

        image_data = await asyncio.to_thread(_read_image_bytes, rel_path)
        if image_data is None:
            await session.proto.async_send_one_message(b"ERR05|Asset not found or unreadable")
        else:
            await session.proto.async_send_one_message(
                serialize_response(ProtocolPrefix.ASSET_START, len(image_data)).encode()
            )
            await session.proto.async_send_one_message(image_data)
        return True

    @staticmethod
    def _sanitize_for_wire_log(message):
        if isinstance(message, str):
            message_text = message
        else:
            message_text = message.decode("utf-8")
        upload_init_prefix = f"{ProtocolCommand.UPLOAD_INIT.value}|"
        if message_text.startswith(upload_init_prefix):
            return message_text, f"{upload_init_prefix}<payload>"
        return message_text, message_text

    async def _dispatch_text_message(self, session, addr, message):
        message_text, log_text = self._sanitize_for_wire_log(message)
        self.logger.info(f" {addr[0]}:{addr[1]} <- {log_text}")

        response = await asyncio.to_thread(session.process_message, message_text)
        if response is None:
            return
        response_preview = response if len(response) < 200 else f"{response[:197]}..."
        self.logger.info(f" {addr[0]}:{addr[1]} -> {response_preview}")
        await session.proto.async_send_one_message(response.encode())

    async def _process_client_message(self, session, addr, message):
        if await self._handle_upload_chunk_message(session, addr, message):
            return
        if await self._handle_asset_binary_message(session, addr, message):
            return
        await self._dispatch_text_message(session, addr, message)

    async def _cleanup_client_session(self, session, addr, websocket):
        if session:
            with self.upload_sessions_lock:
                stale_upload_ids = [uid for uid, s in self.upload_sessions.items() if s.username == session.username]
            for upload_id in stale_upload_ids:
                await asyncio.to_thread(session._cleanup_upload, upload_id)
            self.unregister_session(session)

        with self.clients_lock:
            if addr in self.clients:
                del self.clients[addr]
                self.logger.info(f" Client session removed for {addr[0]}:{addr[1]}")

        await websocket.close()
        self.logger.info(f" Connection closed for {addr[0]}:{addr[1]}")

    async def handle_client(self, websocket):
        """Handle a single WebSocket client connection."""
        session = None
        addr = _normalize_remote_address(getattr(websocket, "remote_address", None))
        loop = asyncio.get_running_loop()
        try:
            self.logger.info(f" Connection attempt from {addr[0]}:{addr[1]}")
            self.logger.info(f" Client connected {addr[0]}:{addr[1]} (session ready)")

            session = ClientSession(websocket, addr, server=self, loop=loop)
            with self.clients_lock:
                self.clients[addr] = session

            while session.is_connected:
                try:
                    message = await session.proto.async_recv_one_message()
                    if message is None:
                        self.logger.info(f" Client {addr[0]}:{addr[1]} disconnected")
                        session.is_connected = False
                        break

                    try:
                        await self._process_client_message(session, addr, message)
                    except Exception as e:
                        self.logger.error(f" Error processing message from {addr[0]}:{addr[1]}: {e}")
                        try:
                            await session.proto.async_send_one_message(f"ERR99|{str(e)}".encode())
                        except Exception:
                            self.logger.error(f" Failed to send error response to {addr[0]}:{addr[1]}")
                            session.is_connected = False
                            break

                except ConnectionClosed:
                    self.logger.info(f" Client {addr[0]}:{addr[1]} closed connection")
                    session.is_connected = False
                except Exception as e:
                    self.logger.error(f" Error in message loop for {addr[0]}:{addr[1]}: {e}")
                    session.is_connected = False

        except Exception as e:
            self.logger.error(f" Critical error in handle_client for {addr[0]}:{addr[1]}: {e}")

        finally:
            try:
                await self._cleanup_client_session(session, addr, websocket)
            except Exception as cleanup_err:
                self.logger.error(f" Error during cleanup for {addr[0]}:{addr[1]}: {cleanup_err}")


# Entry point
if __name__ == "__main__":
    server = Server(
        host=SERVER_HOST,
        port=SERVER_PORT,
    )
    
    server.start()

