from __future__ import annotations

import json
import os
import socket
import ssl
import struct
from typing import Optional

from .models import MarketplaceItem
from .session import UserData, UserSession


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
        if not response.startswith("OK|"):
            parts = response.split("|", 1)
            raise ProtocolError(parts[1] if len(parts) > 1 else response)
        payload = response.split("|", 1)[1]
        items_json = json.loads(payload)
        items = [MarketplaceItem.from_json(item) for item in items_json if isinstance(item, dict)]
        if items_json:
            tail = items_json[-1]
            self.session.last_market_cursor = str(tail.get("created_at") or tail.get("timestamp") or "") or None
        else:
            self.session.last_market_cursor = None
        return items

    def download_asset(self, rel_path: str) -> bytes | None:
        rel_path = rel_path.strip()
        if not rel_path:
            return None
        with self.session.lock:
            self._ensure_connected_unlocked()
            self._send_frame_unlocked(f"GET_ASSET_BINARY|{rel_path}".encode("utf-8"))
            first_frame = self._recv_frame_unlocked()
            text_header = self._try_decode_text(first_frame)
            if text_header is None:
                return self._sanitize_asset_bytes(first_frame)
            if text_header.startswith("ERR"):
                raise ProtocolError(text_header.split("|", 1)[1] if "|" in text_header else text_header)
            if text_header.startswith("ASSET_START|"):
                raw = self._recv_frame_unlocked()
                return self._sanitize_asset_bytes(raw)
            if self._looks_like_chunk_count(text_header):
                raw = self._receive_chunked_binary_with_ack_unlocked(text_header)
                return self._sanitize_asset_bytes(raw)
            raise ProtocolError(f"Unexpected binary header: {text_header}")

    def _request_text(self, command: str) -> str:
        with self.session.lock:
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
        payload = self._recv_frame_unlocked()
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("Expected text frame but received binary data") from exc

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

    def _receive_chunked_binary_with_ack_unlocked(self, text_header: str) -> bytes:
        _, _, raw_count = text_header.partition("|")
        total_parts = int(raw_count)
        collected = bytearray()
        for _ in range(total_parts + 1):
            self._send_frame_unlocked(self.GOT_PART_ACK)
            part = self._recv_frame_unlocked()
            part_text = self._try_decode_text(part)
            if part_text in {"The proccess has ended.", "DONE", "END"}:
                break
            collected.extend(part)
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

        data = raw
        if data.startswith(b"ASSET_START"):
            newline_index = data.find(b"\n")
            pipe_index = data.find(b"|")
            if newline_index >= 0 and newline_index + 1 < len(data):
                data = data[newline_index + 1 :]
            elif pipe_index >= 0 and pipe_index + 1 < len(data):
                data = data[pipe_index + 1 :]

        if not self._has_supported_image_signature(data):
            jpeg_index = self._index_of_signature(data, b"\xff\xd8")
            png_index = self._index_of_signature(data, b"\x89P")
            indexes = [index for index in (jpeg_index, png_index) if index >= 0]
            if indexes:
                data = data[min(indexes) :]

        return data if self._has_supported_image_signature(data) else None
