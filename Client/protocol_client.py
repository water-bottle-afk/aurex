from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .models import ItemOffering, MarketplaceItem, NotificationItem, ServerEvent
from .session import UserData, UserSession
from .wallet import canonical_tx_message, generate_tx_id, get_public_key_base64, sign_message


class ProtocolError(RuntimeError):
    pass


class AurexProtocolClient:
    START_MESSAGE = "START|Client_Flet_App"
    GOT_PART_ACK = b"GOTPRT|Got the part"

    def __init__(
        self,
        session: UserSession,
        host: str | None = None,
        port: int | None = None,
        discovery_port: int = 12345,
    ) -> None:
        self.session = session
        self.host = host or os.getenv("AUREX_SERVER_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("AUREX_SERVER_PORT", "23456"))
        self.discovery_port = discovery_port
        self.on_server_event: Callable[[ServerEvent], None] | None = None

    def discover_server(self, timeout: float = 5.0) -> tuple[str, int] | None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            probe.settimeout(timeout)
            probe.sendto(b"WHRSRV", ("255.255.255.255", self.discovery_port))
            payload, _ = probe.recvfrom(1024)
            message = payload.decode("utf-8", errors="ignore")
            if not message.startswith("SRVRSP|"):
                return None
            parts = message.split("|")
            if len(parts) < 3:
                return None
            return parts[1], int(parts[2])
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
            if discover_first:
                discovered = self.discover_server()
                if discovered is not None:
                    host, port = discovered

            raw_socket = socket.create_connection((host, port), timeout=10)
            context = ssl.create_default_context()
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
            tls_socket = context.wrap_socket(raw_socket, server_hostname=host)
            tls_socket.settimeout(20)

            self.session.socket = tls_socket
            self.session.host = host
            self.session.port = port

            try:
                self._send_frame_unlocked(self.START_MESSAGE.encode("utf-8"))
                response = self._recv_text_frame_unlocked()
                if not response.startswith("ACCPT"):
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

    def login(self, username: str, password: str) -> str:
        username = username.strip()
        if not username or "|" in username or " " in username:
            raise ProtocolError("Invalid username format")
        if not password or "|" in password:
            raise ProtocolError("Invalid password format")
        response = self._request_text(f"LOGIN|{username}|{password}")
        parts = response.split("|")
        if parts[0] == "OK" and len(parts) >= 2:
            returned_username = parts[1]
            self.session.user_data = UserData(username=returned_username)
            return returned_username
        raise ProtocolError(parts[1] if len(parts) > 1 else response)

    def signup(self, username: str, password: str, email: str) -> str:
        username = username.strip()
        email = email.strip()
        if not username or "|" in username or username != username.strip():
            raise ProtocolError("Invalid username")
        if len(password) < 6 or "|" in password or password != password.strip():
            raise ProtocolError("Password must be at least 6 characters")
        if not email or "|" in email or "@" not in email or " " in email:
            raise ProtocolError("Invalid email")
        response = self._request_text(f"SIGNUP|{username}|{password}|{email}")
        parts = response.split("|")
        if parts[0] == "OK":
            return parts[1] if len(parts) > 1 else username
        raise ProtocolError(parts[1] if len(parts) > 1 else response)

    def request_password_reset(self, email: str) -> str | None:
        email = email.strip()
        if not email or "|" in email or " " in email:
            raise ProtocolError("Invalid email")
        response = self._request_text(f"SEND_CODE|{email}")
        parts = response.split("|")
        if parts[0] == "OK":
            return parts[2] if len(parts) > 2 else None
        raise ProtocolError(parts[1] if len(parts) > 1 else response)

    def verify_password_reset_code(self, email: str, code: str) -> str:
        email = email.strip()
        code = code.strip()
        if not email or not code:
            raise ProtocolError("Email and code are required")
        response = self._request_text(f"VERIFY_CODE|{email}|{code}")
        parts = response.split("|")
        if parts[0] == "OK" and len(parts) > 1:
            self.session.reset_token = parts[1]
            return parts[1]
        raise ProtocolError(parts[1] if len(parts) > 1 else response)

    def update_password(self, email: str, new_password: str) -> str:
        email = email.strip()
        if not email or len(new_password) < 6:
            raise ProtocolError("Password must be at least 6 characters")
        response = self._request_text(f"UPDATE_PASSWORD|{email}|{new_password}")
        parts = response.split("|")
        if parts[0] == "OK":
            self.session.reset_token = None
            return parts[1] if len(parts) > 1 else "Password updated successfully"
        raise ProtocolError(parts[1] if len(parts) > 1 else response)

    def logout(self) -> None:
        username = self.session.user_data.username if self.session.user_data else ""
        if self.session.socket is None:
            self.session.clear_user_state()
            return
        try:
            self._request_text(f"LOGOUT|{username}")
        except Exception:
            pass
        finally:
            self.close()

    def get_market_data(
        self,
        limit: int = 10,
        last_timestamp: str | None = None,
    ) -> list[MarketplaceItem]:
        message = f"GET_ITEMS_PAGINATED|{limit}"
        if last_timestamp:
            message = f"{message}|{last_timestamp}"
        response = self._request_text(message)
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
        response = self._request_text("GET_ITEMS")
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
            self._send_frame_unlocked(f"GET_ASSET_BINARY|{rel_path}".encode("utf-8"))
            first_frame = self._recv_frame_unlocked()
            text_header = self._try_decode_text(first_frame)
            if text_header is None:
                return self._sanitize_asset_bytes(first_frame)
            if self._is_error_response(text_header):
                raise ProtocolError(self._extract_error_message(text_header))
            if text_header.startswith("ASSET_START|"):
                size = self._parse_int(text_header.split("|", 1)[1])
                raw = self._recv_frame_unlocked()
                if on_progress:
                    on_progress(1.0 if size else 0.0)
                return self._sanitize_asset_bytes(raw)
            if self._looks_like_chunk_count(text_header):
                raw = self._receive_chunked_binary_with_ack_unlocked(text_header, on_progress=on_progress)
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
        message = f"UPLOAD|{asset_name}|{username}|{google_drive_url}|{file_type}|{cost}"
        response = self._request_text(message)
        if response.startswith("OK"):
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
            init_message = "UPLOAD_INIT|" + base64.b64encode(
                json.dumps(init_payload).encode("utf-8")
            ).decode("ascii")
            self._send_frame_unlocked(init_message.encode("utf-8"))
            init_response = self._recv_text_frame_unlocked()
            init_parts = init_response.split("|")
            if not init_parts or init_parts[0] != "OK":
                raise ProtocolError(self._extract_error_message(init_response))
            upload_id = init_parts[1] if len(init_parts) > 1 else None
            if not upload_id or upload_id == "[]":
                raise ProtocolError("Invalid upload_id from server")
            server_chunk_size = int(init_parts[2]) if len(init_parts) > 2 else preferred_chunk_size
            chunk_size = server_chunk_size if server_chunk_size > 0 else preferred_chunk_size

            sent_chunks = 0
            with open(file_path, "rb") as handle:
                seq = 0
                while True:
                    chunk = handle.read(chunk_size)
                    if not chunk:
                        break
                    payload = b"UPLOAD_CHUNK|" + upload_id.encode("utf-8") + b"|" + struct.pack(">I", seq) + chunk
                    self._send_frame_unlocked(payload)
                    ack = self._recv_text_frame_unlocked()
                    if not (ack == f"OK|{seq}" or ack.startswith("GOTPRT")):
                        raise ProtocolError(f"Chunk {seq} rejected: {self._extract_error_message(ack)}")
                    seq += 1
                    sent_chunks += 1
                    if on_progress:
                        on_progress(min(1.0, sent_chunks / max(total_chunks, 1)))

            self._send_frame_unlocked(f"UPLOAD_FINISH|{upload_id}".encode("utf-8"))
            finish = self._recv_text_frame_unlocked()
            if finish.startswith("OK"):
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
            init_message = "UPLOAD_INIT|" + base64.b64encode(
                json.dumps(init_payload).encode("utf-8")
            ).decode("ascii")
            self._send_frame_unlocked(init_message.encode("utf-8"))
            init_response = self._recv_text_frame_unlocked()
            init_parts = init_response.split("|")
            if not init_parts or init_parts[0] != "OK":
                raise ProtocolError(self._extract_error_message(init_response))
            upload_id = init_parts[1] if len(init_parts) > 1 else None
            if not upload_id or upload_id == "[]":
                raise ProtocolError("Invalid upload_id from server")
            server_chunk_size = int(init_parts[2]) if len(init_parts) > 2 else preferred_chunk_size
            chunk_size = server_chunk_size if server_chunk_size > 0 else preferred_chunk_size

            handle = io.BytesIO(file_bytes)
            sent_chunks = 0
            seq = 0
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    break
                payload = b"UPLOAD_CHUNK|" + upload_id.encode("utf-8") + b"|" + struct.pack(">I", seq) + chunk
                self._send_frame_unlocked(payload)
                ack = self._recv_text_frame_unlocked()
                if not (ack == f"OK|{seq}" or ack.startswith("GOTPRT")):
                    raise ProtocolError(f"Chunk {seq} rejected: {self._extract_error_message(ack)}")
                seq += 1
                sent_chunks += 1
                if on_progress:
                    on_progress(min(1.0, sent_chunks / max(total_chunks, 1)))

            self._send_frame_unlocked(f"UPLOAD_FINISH|{upload_id}".encode("utf-8"))
            finish = self._recv_text_frame_unlocked()
            if finish.startswith("OK"):
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
        public_key = get_public_key_base64()
        payload = {
            "action": "purchase",
            "tx_id": tx_id,
            "asset_id": asset_id,
            "asset_hash": asset_hash,
            "asset_name": asset_name,
            "price": amount,
            "from": username,
            "to": seller,
            "amount": amount,
            "timestamp": timestamp,
        }
        signature = sign_message(canonical_tx_message(username, payload))
        message = (
            f"BUY|{asset_id}|{username}|{amount}|{tx_id}|{timestamp}|{public_key}|{signature}"
        )
        response = self._request_text(message)
        parts = response.split("|")
        if parts[0] == "OK":
            return {"status": parts[1] if len(parts) > 1 else "OK", "tx_id": parts[2] if len(parts) > 2 else None}
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
        public_key = get_public_key_base64()
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
        signature = sign_message(canonical_tx_message(sender_username, payload))
        message = (
            f"SEND|{asset_id}|{sender_username}|{receiver_username}|{tx_id}|{timestamp}|{public_key}|{signature}"
        )
        response = self._request_text(message)
        parts = response.split("|")
        if parts[0] == "OK":
            # Server returns OK|PENDING|tx_id — capture tx_id so caller can poll GET_TX_STATUS.
            returned_tx_id = parts[2] if len(parts) > 2 else tx_id
            return returned_tx_id
        raise ProtocolError(self._extract_error_message(response))

    def get_transaction_status(self, tx_id: str) -> dict[str, str]:
        response = self._request_text(f"GET_TX_STATUS|{tx_id}")
        parts = response.split("|")
        if parts[0] == "OK" and len(parts) >= 2:
            status = parts[1].upper()
            msg = parts[2] if len(parts) > 2 else ""
            return {"status": status, "message": msg}
        raise ProtocolError(self._extract_error_message(response))

    def get_user_assets(self, username: str) -> list[ItemOffering]:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        response = self._request_text(f"GET_ITEMS_BY_USER|{username}")
        payload = self._extract_ok_payload(response)
        decoded = json.loads(payload)
        assets = []
        if isinstance(decoded, list):
            for entry in decoded:
                if isinstance(entry, dict):
                    assets.append(ItemOffering.from_json(entry))
        return assets

    def get_wallet(self, username: str) -> dict[str, Any] | None:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        response = self._request_text(f"GET_WALLET|{username}")
        parts = response.split("|")
        if parts[0] == "OK" and len(parts) >= 2:
            balance = float(parts[1]) if parts[1] else 0.0
            updated_at = parts[2] if len(parts) > 2 else ""
            return {"balance": balance, "updated_at": updated_at}
        if parts[0] == "ERR02":
            return None
        raise ProtocolError(self._extract_error_message(response))

    def get_notifications(self, *, username: str, limit: int = 20) -> tuple[list[NotificationItem], int]:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        response = self._request_text(f"GET_NOTIFICATIONS|{username}|{limit}")
        if response.startswith("ERR02"):
            return [], 0
        first_pipe = response.find("|")
        if response.startswith("OK") and first_pipe != -1:
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
        response = self._request_text(f"MARK_NOTIFICATIONS_READ|{username}")
        return response.startswith("OK")

    def register_device_token(self, *, username: str, platform: str, token: str) -> bool:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        if not token or "|" in token:
            raise ProtocolError("Invalid token")
        response = self._request_text(f"REGISTER_DEVICE|{username}|{platform}|{token}")
        return response.startswith("OK")

    def update_public_key(self, username: str, public_key_b64: str) -> bool:
        """Notify server of a new public key after key regeneration."""
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        if not public_key_b64:
            raise ProtocolError("Missing public key")
        response = self._request_text(f"UPDATE_PUBLIC_KEY|{username}|{public_key_b64}")
        return response.startswith("OK")

    def list_asset_for_sale(self, *, asset_id: str, username: str, price: float) -> str:
        if not asset_id or not username or price <= 0:
            raise ProtocolError("Invalid parameters")
        response = self._request_text(f"LIST_ITEM|{asset_id}|{username}|{price}")
        if response.startswith("OK"):
            return "success"
        raise ProtocolError(self._extract_error_message(response))

    def unlist_asset(self, *, asset_id: str, username: str) -> str:
        if not asset_id or not username:
            raise ProtocolError("Invalid parameters")
        response = self._request_text(f"UNLIST_ITEM|{asset_id}|{username}")
        if response.startswith("OK"):
            return "success"
        raise ProtocolError(self._extract_error_message(response))

    def get_user_profile(self, username: str) -> dict[str, str] | None:
        if not username or "|" in username:
            raise ProtocolError("Invalid username")
        response = self._request_text(f"GET_PROFILE|{username}")
        parts = response.split("|")
        if parts[0] == "OK" and len(parts) >= 4:
            return {"username": parts[1], "email": parts[2], "created_at": parts[3]}
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

    def _ensure_connected_unlocked(self) -> None:
        if self.session.socket is None:
            raise ProtocolError("Not connected to server")

    def _disconnect_unlocked(self, clear_user: bool) -> None:
        sock = self.session.socket
        self.session.socket = None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if clear_user:
            self.session.clear_user_state()

    def _send_frame_unlocked(self, data: bytes) -> None:
        self._ensure_connected_unlocked()
        assert self.session.socket is not None
        self.session.socket.sendall(struct.pack(">I", len(data)) + data)

    def _recv_frame_unlocked(self) -> bytes:
        header = self._recv_exact_unlocked(4)
        if not header:
            raise ProtocolError("Socket closed by server")
        frame_length = struct.unpack(">I", header)[0]
        return self._recv_exact_unlocked(frame_length)

    def _recv_text_frame_unlocked(self) -> str:
        while True:
            payload = self._recv_frame_unlocked()
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProtocolError("Expected text frame but received binary data") from exc

            if text.startswith("EVENT|"):
                json_str = text[6:]
                try:
                    event = ServerEvent.from_json(json_str)
                    self.session.server_events.append(event)
                    if self.on_server_event:
                        self.on_server_event(event)
                except Exception:
                    pass
                continue
            return text

    def _recv_exact_unlocked(self, size: int) -> bytes:
        self._ensure_connected_unlocked()
        assert self.session.socket is not None
        chunks: list[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = self.session.socket.recv(remaining)
            if not chunk:
                raise ProtocolError("Socket closed during receive")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _looks_like_chunk_count(self, text_header: str) -> bool:
        prefixes = ("PARTS|", "NUMPRT|", "AMNPRT|")
        return text_header.startswith(prefixes)

    def _receive_chunked_binary_with_ack_unlocked(
        self,
        text_header: str,
        *,
        on_progress: Callable[[float], None] | None = None,
    ) -> bytes:
        _, _, raw_count = text_header.partition("|")
        total_parts = int(raw_count) if raw_count.isdigit() else 0
        collected = bytearray()
        for idx in range(total_parts + 1):
            self._send_frame_unlocked(self.GOT_PART_ACK)
            part = self._recv_frame_unlocked()
            part_text = self._try_decode_text(part)
            if part_text in {"The proccess has ended.", "DONE", "END"}:
                break
            collected.extend(part)
            if on_progress and total_parts:
                on_progress(min(1.0, (idx + 1) / max(total_parts, 1)))
        return bytes(collected)

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
        if response.startswith("OK|"):
            return response.split("|", 1)[1]
        raise ProtocolError(self._extract_error_message(response))

    def _extract_error_message(self, response: str) -> str:
        if "|" in response:
            return response.split("|", 1)[1]
        return response

    def _is_error_response(self, response: str) -> bool:
        return response.startswith(("ERR", "PTHERR", "GRLERR"))

    def _parse_int(self, raw: str) -> int:
        try:
            return int(raw)
        except Exception:
            return 0
