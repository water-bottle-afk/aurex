from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import socket
import ssl
import struct
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import websockets
from websockets.exceptions import ConnectionClosed

from aurex_logging import AurexLogger
from protocol_definitions import (
    CLIENT_IDENTITY,
    EVENT_PREFIX,
    UPLOAD_CHUNK_PREFIX,
    DiscoveryRequest,
    DiscoveryResponse,
    ProtocolCommand,
    ProtocolPrefix,
    is_error_response,
    join_wire_fields,
    parse_wire_message,
    serialize_command,
    serialize_response,
)
from .models import ItemOffering, MarketplaceItem, NotificationItem, ServerEvent
from .session import UserData, UserSession
from .wallet import (
    activate_wallet_user,
    canonical_tx_message,
    generate_tx_id,
    get_public_key_base64,
    sign_message,
)

try:
    from blockchain.networking import build_protocol_message as build_encrypted_protocol_message
    from blockchain.networking import discover_gateway as discover_encrypted_gateway
    from blockchain.networking import EncryptedClient as AurexEncryptedClient
except Exception:  # pragma: no cover - fallback for environments without blockchain module path
    build_encrypted_protocol_message = None
    discover_encrypted_gateway = None
    AurexEncryptedClient = None


class ProtocolError(RuntimeError):
    pass


logger = AurexLogger.get_logger(__name__)


class AurexProtocolClient:
    START_MESSAGE = serialize_command(ProtocolCommand.START, CLIENT_IDENTITY)

    def __init__(
        self,
        session: UserSession,
        host: str | None = None,
        port: int | None = None,
        discovery_port: int = 12345,
    ) -> None:
        self.session = session
        self.host = host or os.getenv("AUREX_SERVER_HOST", "10.100.102.58")
        self.port = port or int(os.getenv("AUREX_SERVER_PORT", "23456"))
        self.discovery_port = discovery_port
        self.enable_udp_discovery = os.getenv("AUREX_ENABLE_UDP_DISCOVERY", "0") == "1"
        self.enable_encrypted_gateway = os.getenv("AUREX_UI_ENCRYPTED_GATEWAY", "0") == "1"
        self.encrypted_gateway_host = os.getenv("AUREX_GATEWAY_HOST", "").strip()
        self.encrypted_gateway_port = int(os.getenv("AUREX_GATEWAY_PORT", "5000"))
        self.on_server_event: Callable[[ServerEvent], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._loop_ready = threading.Event()
        self._incoming_frames: queue.Queue[Any] = queue.Queue()
        self._receiver_closed = object()
        self._receive_timeout = 20.0
        self._receiver_task = None

    def discover_server(self, timeout: float = 5.0) -> tuple[str, int] | None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            probe.settimeout(timeout)
            probe.sendto(DiscoveryRequest().to_bytes(), ("255.255.255.255", self.discovery_port))
            payload, _ = probe.recvfrom(1024)
            message = payload.decode("utf-8", errors="ignore")
            parsed = DiscoveryResponse.from_text(message)
            if parsed is None:
                return None
            return parsed.host, parsed.port
        except OSError:
            return None
        finally:
            probe.close()

    def connect(self, discover_first: bool = True) -> None:
        with self.session.lock:
            if self.session.socket is not None:
                return

            host = self.session.host or self.host
            port = self.session.port or self.port
            if discover_first and self.enable_udp_discovery:
                discovered = self.discover_server()
                if discovered is not None:
                    host, port = discovered

            self._ensure_loop_thread()
            self._incoming_frames = queue.Queue()
            websocket = self._run_coro_sync(self._connect_async(host, port), timeout=20)

            self.session.socket = websocket
            self.session.host = host
            self.session.port = port

            try:
                self._send_frame_unlocked(self.START_MESSAGE.encode("utf-8"))
                response = self._recv_text_frame_unlocked()
                head, _ = self._split_response(response)
                if head != ProtocolPrefix.ACCEPT.value:
                    raise ProtocolError(f"Unexpected START response: {response}")
                self.session.remember(f"Connected to {host}:{port}")
            except Exception:
                self._disconnect_unlocked(clear_user=False)
                raise

    def close(self) -> None:
        with self.session.lock:
            self._disconnect_unlocked(clear_user=True)

    def set_server_address(self, host: str, port: int) -> None:
        with self.session.lock:
            self.session.host = host
            self.session.port = port
            self.host = host
            self.port = port

    def _build_server_uri(self, host: str, port: int) -> str:
        return f"wss://{host}:{port}"

    def _resolve_ca_cert_path(self) -> Path:
        configured = os.getenv("AUREX_CA_CERT_FILE", "").strip()
        if configured:
            cert_path = Path(configured).expanduser()
            if not cert_path.is_absolute():
                cert_path = (Path(__file__).resolve().parent.parent / cert_path).resolve()
        else:
            cert_path = (Path(__file__).resolve().parent.parent / "HTTPS" / "rootCA.crt").resolve()
        return cert_path

    def login(self, username: str, password: str) -> str:
        username = username.strip()
        if not username or "|" in username or " " in username:
            raise ProtocolError("Invalid username format")
        if not password or "|" in password:
            raise ProtocolError("Invalid password format")
        response = self._request_command(ProtocolCommand.LOGIN, username, password)
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value and parts:
            returned_username = parts[0]
            activate_wallet_user(returned_username, password=password, ensure_keys=True)
            self.session.user_data = UserData(username=returned_username)
            return returned_username
        raise ProtocolError(parts[0] if parts else response)

    def signup(self, username: str, password: str, email: str, public_key_b64: str | None = None) -> str:
        username = username.strip()
        email = email.strip()
        if not username or "|" in username or username != username.strip():
            raise ProtocolError("Invalid username")
        if len(password) < 6 or "|" in password or password != password.strip():
            raise ProtocolError("Password must be at least 6 characters")
        if not email or "|" in email or "@" not in email or " " in email:
            raise ProtocolError("Invalid email")
        request_parts: list[str] = [username, password, email]
        if public_key_b64:
            request_parts.append(public_key_b64)
        request = serialize_command(ProtocolCommand.SIGNUP, *request_parts)
        response = self._request_text(request)
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value:
            return parts[0] if parts else username
        raise ProtocolError(parts[0] if parts else response)

    def request_password_reset(self, email: str) -> str | None:
        email = email.strip()
        if not email or "|" in email or " " in email:
            raise ProtocolError("Invalid email")
        response = self._request_command(ProtocolCommand.SEND_CODE, email)
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value:
            return parts[1] if len(parts) > 1 else None
        raise ProtocolError(parts[0] if parts else response)

    def verify_password_reset_code(self, email: str, code: str) -> str:
        email = email.strip()
        code = code.strip()
        if not email or not code:
            raise ProtocolError("Email and code are required")
        response = self._request_command(ProtocolCommand.VERIFY_CODE, email, code)
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value and parts:
            self.session.reset_token = parts[0]
            return parts[0]
        raise ProtocolError(parts[0] if parts else response)

    def update_password(self, email: str, new_password: str) -> str:
        email = email.strip()
        if not email or len(new_password) < 6:
            raise ProtocolError("Password must be at least 6 characters")
        response = self._request_command(ProtocolCommand.UPDATE_PASSWORD, email, new_password)
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value:
            self.session.reset_token = None
            return parts[0] if parts else "Password updated successfully"
        raise ProtocolError(parts[0] if parts else response)

    def logout(self) -> None:
        username = self.session.user_data.username if self.session.user_data else ""
        if self.session.socket is None:
            self.session.clear_user_state()
            return
        try:
            self._request_command(ProtocolCommand.LOGOUT, username)
        except Exception:
            pass
        finally:
            self.close()

    def get_wallet(self, username: str) -> float | None:
        """Send GET_WALLET|username, return balance as float or None on error."""
        response = self._request_command(ProtocolCommand.GET_WALLET, username)
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value and parts:
            try:
                return float(parts[0])
            except ValueError:
                return None
        return None

    def get_market_data(
        self,
        limit: int = 10,
        last_timestamp: str | None = None,
    ) -> list[MarketplaceItem]:
        if last_timestamp:
            response = self._request_command(ProtocolCommand.GET_ITEMS_PAGINATED, limit, last_timestamp)
        else:
            response = self._request_command(ProtocolCommand.GET_ITEMS_PAGINATED, limit)
        payload = self._extract_ok_payload(response)
        items_json = json.loads(payload)
        items = [MarketplaceItem.from_json(item) for item in items_json if isinstance(item, dict)]
        if items_json:
            tail = items_json[-1]
            self.session.last_market_cursor = str(tail.get("created_at") or tail.get("timestamp") or "") or None
        else:
            self.session.last_market_cursor = None
        return items

    def get_items(self) -> list[MarketplaceItem]:
        response = self._request_command(ProtocolCommand.GET_ITEMS)
        payload = self._extract_ok_payload(response)
        items_json = json.loads(payload)
        return [MarketplaceItem.from_json(item) for item in items_json if isinstance(item, dict)]

    def download_asset(
        self,
        rel_path: str,
        *,
        on_progress: Callable[[float], None] | None = None,
    ) -> bytes | None:
        rel_path = rel_path.strip()
        if not rel_path:
            return None
        with self.session.socket_lock:
            self._ensure_connected_unlocked()
            self._send_frame_unlocked(
                serialize_command(ProtocolCommand.GET_ASSET_BINARY, rel_path).encode("utf-8")
            )
            first_frame = self._recv_frame_unlocked()
            text_header = self._try_decode_text(first_frame)
            if text_header is None:
                return self._sanitize_asset_bytes(first_frame)
            if self._is_error_response(text_header):
                raise ProtocolError(self._extract_error_message(text_header))
            if text_header.startswith(f"{ProtocolPrefix.ASSET_START.value}|"):
                size = self._parse_int(text_header.split("|", 1)[1])
                raw = self._recv_frame_unlocked()
                if on_progress:
                    on_progress(1.0 if size else 0.0)
                return self._sanitize_asset_bytes(raw)
            raise ProtocolError(f"Unexpected binary header: {text_header}")

    def upload_marketplace_item(
        self,
        *,
        asset_name: str,
        username: str,
        google_drive_url: str,
        file_type: str,
        cost: float,
    ) -> str:
        response = self._request_command(
            ProtocolCommand.UPLOAD,
            asset_name,
            username,
            google_drive_url,
            file_type,
            cost,
        )
        if response.startswith(ProtocolPrefix.OK.value):
            return "success"
        raise ProtocolError(self._extract_error_message(response))

    def upload_marketplace_item_binary(
        self,
        *,
        file_path: str,
        asset_name: str,
        description: str,
        username: str,
        file_type: str,
        cost: float,
        asset_hash: str,
        mint_tx_id: str,
        mint_timestamp: str,
        public_key: str,
        mint_signature: str,
        on_progress: Callable[[float], None] | None = None,
        preferred_chunk_size: int = 2048,
    ) -> str:
        upload_id: str | None = None
        file_type = file_type.lower().replace("jpeg", "jpg")
        with self.session.socket_lock:
            self._ensure_connected_unlocked()
            file_size = os.path.getsize(file_path)
            total_chunks = (file_size + preferred_chunk_size - 1) // preferred_chunk_size
            init_payload = {
                "asset_name": asset_name,
                "username": username,
                "description": description,
                "file_type": file_type,
                "cost": cost,
                "file_size": file_size,
                "original_name": os.path.basename(file_path),
                "total_chunks": total_chunks,
                "asset_hash": asset_hash,
                "mint_tx_id": mint_tx_id,
                "mint_timestamp": mint_timestamp,
                "public_key": public_key,
                "mint_signature": mint_signature,
            }
            init_message = join_wire_fields(
                ProtocolCommand.UPLOAD_INIT.value,
                base64.b64encode(json.dumps(init_payload).encode("utf-8")).decode("ascii"),
            )
            self._send_frame_unlocked(init_message.encode("utf-8"))
            init_response = self._recv_text_frame_unlocked()
            init_head, init_parts = self._split_response(init_response)
            if init_head != ProtocolPrefix.OK.value:
                raise ProtocolError(self._extract_error_message(init_response))
            upload_id = init_parts[0] if init_parts else None
            if not upload_id or upload_id == "[]":
                raise ProtocolError("Invalid upload_id from server")
            server_chunk_size = int(init_parts[1]) if len(init_parts) > 1 else preferred_chunk_size
            chunk_size = server_chunk_size if server_chunk_size > 0 else preferred_chunk_size

            sent_chunks = 0
            with open(file_path, "rb") as handle:
                seq = 0
                while True:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    payload = UPLOAD_CHUNK_PREFIX + upload_id.encode("utf-8") + b"|" + struct.pack(">I", seq) + chunk
                    self._send_frame_unlocked(payload)
                    ack = self._recv_text_frame_unlocked()
                    if not (
                        ack == serialize_response(ProtocolPrefix.OK, seq)
                        or ack.startswith(ProtocolPrefix.GOTPRT.value)
                    ):
                        raise ProtocolError(f"Chunk {seq} rejected: {self._extract_error_message(ack)}")
                    seq += 1
                    sent_chunks += 1
                    if on_progress:
                        on_progress(min(1.0, sent_chunks / max(total_chunks, 1)))

            self._send_frame_unlocked(
                serialize_command(ProtocolCommand.UPLOAD_FINISH, upload_id).encode("utf-8")
            )
            finish = self._recv_text_frame_unlocked()
            if finish.startswith(ProtocolPrefix.OK.value):
                return "success"
            raise ProtocolError(self._extract_error_message(finish))

    def upload_marketplace_item_from_bytes(
        self,
        *,
        file_bytes: bytes,
        file_name: str,
        asset_name: str,
        description: str,
        username: str,
        file_type: str,
        cost: float,
        asset_hash: str,
        mint_tx_id: str,
        mint_timestamp: str,
        public_key: str,
        mint_signature: str,
        on_progress: Callable[[float], None] | None = None,
        preferred_chunk_size: int = 32768,
    ) -> str:
        """Upload from raw bytes (web mode where file.path is unavailable)."""
        import io
        file_type = file_type.lower().replace("jpeg", "jpg")
        file_size = len(file_bytes)
        total_chunks = (file_size + preferred_chunk_size - 1) // preferred_chunk_size
        with self.session.socket_lock:
            self._ensure_connected_unlocked()
            init_payload = {
                "asset_name": asset_name,
                "username": username,
                "description": description,
                "file_type": file_type,
                "cost": cost,
                "file_size": file_size,
                "original_name": file_name,
                "total_chunks": total_chunks,
                "asset_hash": asset_hash,
                "mint_tx_id": mint_tx_id,
                "mint_timestamp": mint_timestamp,
                "public_key": public_key,
                "mint_signature": mint_signature,
            }
            init_message = join_wire_fields(
                ProtocolCommand.UPLOAD_INIT.value,
                base64.b64encode(json.dumps(init_payload).encode("utf-8")).decode("ascii"),
            )
            self._send_frame_unlocked(init_message.encode("utf-8"))
            init_response = self._recv_text_frame_unlocked()
            init_head, init_parts = self._split_response(init_response)
            if init_head != ProtocolPrefix.OK.value:
                raise ProtocolError(self._extract_error_message(init_response))
            upload_id = init_parts[0] if init_parts else None
            if not upload_id or upload_id == "[]":
                raise ProtocolError("Invalid upload_id from server")
            server_chunk_size = int(init_parts[1]) if len(init_parts) > 1 else preferred_chunk_size
            chunk_size = server_chunk_size if server_chunk_size > 0 else preferred_chunk_size

            handle = io.BytesIO(file_bytes)
            sent_chunks = 0
            seq = 0
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                payload = UPLOAD_CHUNK_PREFIX + upload_id.encode("utf-8") + b"|" + struct.pack(">I", seq) + chunk
                self._send_frame_unlocked(payload)
                ack = self._recv_text_frame_unlocked()
                if not (
                    ack == serialize_response(ProtocolPrefix.OK, seq)
                    or ack.startswith(ProtocolPrefix.GOTPRT.value)
                ):
                    raise ProtocolError(f"Chunk {seq} rejected: {self._extract_error_message(ack)}")
                seq += 1
                sent_chunks += 1
                if on_progress:
                    on_progress(min(1.0, sent_chunks / max(total_chunks, 1)))

            self._send_frame_unlocked(
                serialize_command(ProtocolCommand.UPLOAD_FINISH, upload_id).encode("utf-8")
            )
            finish = self._recv_text_frame_unlocked()
            if finish.startswith(ProtocolPrefix.OK.value):
                return "success"
            raise ProtocolError(self._extract_error_message(finish))

    # NOTE: upload_asset_chunked was removed — it sent UPLOAD_START which has no
    # server handler. All uploads must go through upload_marketplace_item_binary
    # or upload_marketplace_item_from_bytes (UPLOAD_INIT -> UPLOAD_CHUNK -> UPLOAD_FINISH).

    def buy_asset(
        self,
        *,
        asset_id: str,
        username: str,
        amount: float,
        asset_name: str,
        seller: str,
        asset_hash: str,
    ) -> dict[str, Any]:
        if not asset_hash:
            raise ProtocolError("Missing asset hash")
        tx_id = generate_tx_id("TXN", username, asset_id=asset_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        public_key = get_public_key_base64(username)
        payload = {
            "action": "asset_purchase",
            "tx_id": tx_id,
            "asset_id": asset_id,
            "asset_hash": asset_hash,
            "asset_name": asset_name,
            "buyer_pub": public_key,
            "price": amount,
            "from": username,
            "to": seller,
            "amount": amount,
            "timestamp": timestamp,
        }
        signature = sign_message(canonical_tx_message(username, payload), username)
        encrypted_response = self._submit_encrypted_gateway_transaction(
            tx_type="ASSET_PURCHASE",
            payload=payload,
            public_key=public_key,
            signature=signature,
            tx_id=tx_id,
        )
        if encrypted_response is not None and encrypted_response.get("status") in {"submitted", "ok"}:
            return encrypted_response
        response = self._request_command(
            ProtocolCommand.BUY,
            asset_id,
            username,
            amount,
            tx_id,
            timestamp,
            public_key,
            signature,
        )
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value:
            return {"status": parts[0] if parts else "OK", "tx_id": parts[1] if len(parts) > 1 else None}
        raise ProtocolError(self._extract_error_message(response))

    def send_asset_to_user(
        self,
        *,
        asset_id: str,
        sender_username: str,
        receiver_username: str,
        asset_name: str,
        asset_hash: str,
    ) -> str:
        if not asset_hash:
            raise ProtocolError("Missing asset hash")
        tx_id = generate_tx_id("SEND", sender_username, asset_id=asset_id)
        timestamp = datetime.now(timezone.utc).isoformat()
        public_key = get_public_key_base64(sender_username)
        payload = {
            "action": "asset_transfer",
            "tx_id": tx_id,
            "asset_id": asset_id,
            "asset_hash": asset_hash,
            "asset_name": asset_name,
            "from": sender_username,
            "to": receiver_username,
            "amount": 0,
            "timestamp": timestamp,
        }
        signature = sign_message(canonical_tx_message(sender_username, payload), sender_username)
        encrypted_response = self._submit_encrypted_gateway_transaction(
            tx_type="ASSET_TRANSFER",
            payload=payload,
            public_key=public_key,
            signature=signature,
            tx_id=tx_id,
        )
        if encrypted_response is not None and encrypted_response.get("status") in {"submitted", "ok"}:
            return tx_id
        response = self._request_command(
            ProtocolCommand.SEND,
            asset_id,
            sender_username,
            receiver_username,
            tx_id,
            timestamp,
            public_key,
            signature,
        )
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value:
            # Server returns OK|PENDING|tx_id; capture tx_id so caller can poll GET_TX_STATUS.
            returned_tx_id = parts[1] if len(parts) > 1 else tx_id
            return returned_tx_id
        raise ProtocolError(self._extract_error_message(response))

    def _resolve_encrypted_gateway(self) -> tuple[str, int] | None:
        if self.encrypted_gateway_host:
            return self.encrypted_gateway_host, self.encrypted_gateway_port
        if discover_encrypted_gateway is None:
            return None
        try:
            return discover_encrypted_gateway(timeout=2.5)
        except Exception:
            return None

    def _submit_encrypted_gateway_transaction(
        self,
        *,
        tx_type: str,
        payload: dict[str, Any],
        public_key: str,
        signature: str,
        tx_id: str,
    ) -> dict[str, Any] | None:
        if not self.enable_encrypted_gateway:
            return None
        if AurexEncryptedClient is None or build_encrypted_protocol_message is None:
            return None
        endpoint = self._resolve_encrypted_gateway()
        if endpoint is None:
            return None
        host, port = endpoint
        tx_obj = {
            "tx_type": tx_type,
            "payload": payload,
            "public_key": public_key,
            "signature": signature,
            "timestamp": datetime.now(timezone.utc).timestamp(),
        }
        try:
            response = AurexEncryptedClient(host, port, timeout=8.0).request(
                build_encrypted_protocol_message("SUBMIT_TRANSACTION", {"transaction": tx_obj}),
                expect_response=True,
            )
            if not response:
                return {"status": "failed", "tx_id": tx_id}
            if response.get("type") == "TX_SUBMIT_RESULT":
                details = response.get("payload") or {}
                status = "submitted" if details.get("ok") else "failed"
                return {"status": status, "tx_id": tx_id, "details": details}
            return {"status": "failed", "tx_id": tx_id}
        except Exception:
            return {"status": "failed", "tx_id": tx_id}

    def get_transaction_status(self, tx_id: str) -> dict[str, str]:
        response = self._request_command(ProtocolCommand.GET_TX_STATUS, tx_id)
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value and parts:
            status = parts[0].upper()
            msg = parts[1] if len(parts) > 1 else ""
            return {"status": status, "message": msg}
        raise ProtocolError(self._extract_error_message(response))

    def get_user_assets(self, username: str) -> list[ItemOffering]:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        response = self._request_command(ProtocolCommand.GET_ITEMS_BY_USER, username)
        payload = self._extract_ok_payload(response)
        decoded = json.loads(payload)
        assets = []
        if isinstance(decoded, list):
            for entry in decoded:
                if isinstance(entry, dict):
                    assets.append(ItemOffering.from_json(entry))
        return assets

    # get_wallet is defined earlier in this class (returns float | None)

    def get_notifications(self, *, username: str, limit: int = 20) -> tuple[list[NotificationItem], int]:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        response = self._request_command(ProtocolCommand.GET_NOTIFICATIONS, username, limit)
        if response.startswith("ERR02"):
            return [], 0
        first_pipe = response.find("|")
        if response.startswith(ProtocolPrefix.OK.value) and first_pipe != -1:
            last_pipe = response.rfind("|")
            json_str = response[first_pipe + 1 : last_pipe if last_pipe != first_pipe else None]
            unread_str = response[last_pipe + 1 :] if last_pipe != first_pipe else "0"
            decoded = json.loads(json_str) if json_str else []
            items: list[NotificationItem] = []
            if isinstance(decoded, list):
                for entry in decoded:
                    if isinstance(entry, dict):
                        items.append(NotificationItem.from_map(entry))
            unread_count = int(unread_str) if unread_str.isdigit() else 0
            return items, unread_count
        raise ProtocolError(self._extract_error_message(response))

    def mark_notifications_read(self, username: str) -> bool:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        response = self._request_command(ProtocolCommand.MARK_NOTIFICATIONS_READ, username)
        return response.startswith(ProtocolPrefix.OK.value)

    def register_device_token(self, *, username: str, platform: str, token: str) -> bool:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        if not token or "|" in token:
            raise ProtocolError("Invalid token")
        response = self._request_command(ProtocolCommand.REGISTER_DEVICE, username, platform, token)
        return response.startswith(ProtocolPrefix.OK.value)

    def update_public_key(self, username: str, public_key_b64: str) -> bool:
        """Notify server of a new public key after key regeneration."""
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        if not public_key_b64:
            raise ProtocolError("Missing public key")
        response = self._request_command(ProtocolCommand.UPDATE_PUBLIC_KEY, username, public_key_b64)
        return response.startswith(ProtocolPrefix.OK.value)

    def list_asset_for_sale(self, *, asset_id: str, username: str, price: float) -> str:
        if not asset_id or not username or price <= 0:
            raise ProtocolError("Invalid parameters")
        response = self._request_command(ProtocolCommand.LIST_ITEM, asset_id, username, price)
        if response.startswith(ProtocolPrefix.OK.value):
            return "success"
        raise ProtocolError(self._extract_error_message(response))

    def unlist_asset(self, *, asset_id: str, username: str) -> str:
        if not asset_id or not username:
            raise ProtocolError("Invalid parameters")
        response = self._request_command(ProtocolCommand.UNLIST_ITEM, asset_id, username)
        if response.startswith(ProtocolPrefix.OK.value):
            return "success"
        raise ProtocolError(self._extract_error_message(response))

    def get_user_profile(self, username: str) -> dict[str, str] | None:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        response = self._request_command(ProtocolCommand.GET_PROFILE, username)
        head, parts = self._split_response(response)
        if head == ProtocolPrefix.OK.value and len(parts) >= 3:
            return {"username": parts[0], "email": parts[1], "created_at": parts[2]}
        raise ProtocolError(self._extract_error_message(response))

    def sha256_file(self, file_path: str) -> str:
        import hashlib

        hasher = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def _request_text(self, command: str) -> str:
        with self.session.socket_lock:
            self._ensure_connected_unlocked()
            self._send_frame_unlocked(command.encode("utf-8"))
            return self._recv_text_frame_unlocked()

    def _request_command(self, command: ProtocolCommand, *parts: Any) -> str:
        return self._request_text(serialize_command(command, *parts))

    def _split_response(self, response: str) -> tuple[str, list[str]]:
        parsed = parse_wire_message(response)
        return parsed.head, list(parsed.parts)

    def _ensure_connected_unlocked(self) -> None:
        if self.session.socket is None:
            raise ProtocolError("Not connected to server")

    def _disconnect_unlocked(self, clear_user: bool) -> None:
        websocket = self.session.socket
        self.session.socket = None
        if websocket is not None:
            try:
                self._run_coro_sync(self._close_async(websocket), timeout=10)
            except Exception:
                pass
        if clear_user:
            self.session.clear_user_state()

    def _send_frame_unlocked(self, data: bytes) -> None:
        self._ensure_connected_unlocked()
        self._run_coro_sync(self._send_async(data), timeout=30)

    def _recv_frame_unlocked(self) -> bytes:
        try:
            payload = self._incoming_frames.get(timeout=self._receive_timeout)
        except queue.Empty as exc:
            raise ProtocolError("Timed out waiting for server response") from exc

        if payload is self._receiver_closed:
            raise ProtocolError("WebSocket closed by server")
        if isinstance(payload, Exception):
            raise payload
        if isinstance(payload, str):
            return payload.encode("utf-8")
        return payload

    def _recv_text_frame_unlocked(self) -> str:
        while True:
            payload = self._recv_frame_unlocked()
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProtocolError("Expected text frame but received binary data") from exc

            return text

    def _try_decode_text(self, payload: bytes) -> Optional[str]:
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def _has_supported_image_signature(self, payload: bytes) -> bool:
        return len(payload) >= 2 and (
            payload.startswith(b"\xff\xd8") or payload.startswith(b"\x89P")
        )

    def _index_of_signature(self, payload: bytes, signature: bytes) -> int:
        return payload.find(signature)

    def _sanitize_asset_bytes(self, raw: bytes) -> bytes | None:
        if not raw:
            return None

        # NOTE: ASSET_START header strip was removed — server now sends two separate
        # framed messages (text header + raw binary), so the binary frame never
        # contains an ASSET_START prefix. The strip was dead code from an old protocol.
        data = raw
        if not self._has_supported_image_signature(data):
            jpeg_index = self._index_of_signature(data, b"\xff\xd8")
            png_index = self._index_of_signature(data, b"\x89P")
            indexes = [index for index in (jpeg_index, png_index) if index >= 0]
            if indexes:
                data = data[min(indexes) :]

        return data if self._has_supported_image_signature(data) else None

    def _extract_ok_payload(self, response: str) -> str:
        ok_prefix = f"{ProtocolPrefix.OK.value}|"
        if response.startswith(ok_prefix):
            return response[len(ok_prefix):]
        raise ProtocolError(self._extract_error_message(response))

    def _extract_error_message(self, response: str) -> str:
        if "|" in response:
            return response.split("|", 1)[1]
        return response

    def _is_error_response(self, response: str) -> bool:
        return is_error_response(response)

    def _parse_int(self, raw: str) -> int:
        try:
            return int(raw)
        except Exception:
            return 0

    def _ensure_loop_thread(self) -> None:
        if self._loop_thread and self._loop_thread.is_alive() and self._loop is not None:
            return
        self._loop_ready.clear()
        self._loop_thread = threading.Thread(target=self._loop_worker, daemon=True)
        self._loop_thread.start()
        self._loop_ready.wait(timeout=5)
        if self._loop is None:
            raise ProtocolError("Failed to start WebSocket event loop")

    def _loop_worker(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._loop_ready.set()
        loop.run_forever()

    def _run_coro_sync(self, coro, *, timeout: float | None = None):
        self._ensure_loop_thread()
        assert self._loop is not None
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _connect_async(self, host: str, port: int):
        ssl_context = ssl.create_default_context()
        if hasattr(ssl, "VERIFY_X509_STRICT"):
            # Python/OpenSSL strict chain checks may reject older local cert chains
            # with "Missing Authority Key Identifier"; keep CA validation enabled.
            ssl_context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        ca_cert_path = self._resolve_ca_cert_path()
        if not ca_cert_path.exists():
            raise ProtocolError(f"CA certificate not found: {ca_cert_path}")
        ssl_context.load_verify_locations(cafile=str(ca_cert_path))
        uri = self._build_server_uri(host, port)
        frame_queue = self._incoming_frames
        websocket = await websockets.connect(
            uri,
            ssl=ssl_context,
            max_size=None,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
        )
        self._receiver_task = asyncio.create_task(self._receiver_loop(websocket, frame_queue))
        return websocket

    async def _close_async(self, websocket) -> None:
        try:
            await websocket.close()
        except Exception:
            pass

    async def _send_async(self, data: bytes) -> None:
        self._ensure_connected_unlocked()
        assert self.session.socket is not None
        payload: str | bytes
        if data.startswith(UPLOAD_CHUNK_PREFIX):
            payload = data
        else:
            try:
                payload = data.decode("utf-8")
            except UnicodeDecodeError:
                payload = data
        await self.session.socket.send(payload)

    async def _receiver_loop(self, websocket, frame_queue: queue.Queue[Any]) -> None:
        try:
            async for payload in websocket:
                if isinstance(payload, str) and payload.startswith(EVENT_PREFIX):
                    self._handle_server_event(payload)
                    continue
                frame_queue.put(payload)
        except ConnectionClosed:
            pass
        except Exception as exc:
            frame_queue.put(ProtocolError(str(exc)))
        finally:
            frame_queue.put(self._receiver_closed)

    def _handle_server_event(self, payload: str) -> None:
        json_str = payload[len(EVENT_PREFIX):]
        try:
            event = ServerEvent.from_json(json_str)
            self.session.server_events.append(event)
            if self.on_server_event:
                self.on_server_event(event)
        except Exception:
            pass



