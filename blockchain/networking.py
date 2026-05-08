"""Aurex encrypted networking primitives and UDP discovery helpers."""

from __future__ import annotations

import json
import os
import socket
import struct
from pathlib import Path
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, padding as sym_padding, serialization
from cryptography.hazmat.primitives.asymmetric import padding as asym_padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

AUREX_DISCOVERY_REQUEST = "AUREX_DISCOVERY_REQUEST"
AUREX_DISCOVERY_RESPONSE = "AUREX_DISCOVERY_RESPONSE"
AUREX_DISCOVERY_PORT = 5005

MAX_FRAME_SIZE = 16 * 1024 * 1024


def build_protocol_message(msg_type: str, payload: dict[str, Any], signature: str | None = None) -> dict[str, Any]:
    """Build a strict AUREX_PROTOCOL message envelope."""
    message: dict[str, Any] = {"type": msg_type, "payload": payload}
    if signature:
        message["signature"] = signature
    return message


def validate_protocol_message(raw: dict[str, Any]) -> tuple[bool, str]:
    """Validate message schema: {'type': ..., 'payload': ..., 'signature': optional}."""
    if not isinstance(raw, dict):
        return False, "message must be a JSON object"
    if "type" not in raw:
        return False, "missing type"
    if "payload" not in raw:
        return False, "missing payload"
    if not isinstance(raw["type"], str) or not raw["type"]:
        return False, "type must be a non-empty string"
    if not isinstance(raw["payload"], dict):
        return False, "payload must be an object"
    if "signature" in raw and raw["signature"] is not None and not isinstance(raw["signature"], str):
        return False, "signature must be a string if provided"
    return True, "ok"


def _send_frame(sock: socket.socket, payload: bytes) -> None:
    if len(payload) > MAX_FRAME_SIZE:
        raise ValueError("payload too large")
    sock.sendall(struct.pack(">I", len(payload)) + payload)


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("socket closed during recv")
        data += chunk
    return data


def _recv_frame(sock: socket.socket) -> bytes:
    header = _recv_exact(sock, 4)
    (size,) = struct.unpack(">I", header)
    if size > MAX_FRAME_SIZE:
        raise ValueError("frame too large")
    return _recv_exact(sock, size)


def _aes_encrypt(aes_key: bytes, plaintext: bytes) -> bytes:
    iv = os.urandom(16)
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return iv + ciphertext


def _aes_decrypt(aes_key: bytes, data: bytes) -> bytes:
    if len(data) < 16:
        raise ValueError("encrypted payload too short")
    iv, ciphertext = data[:16], data[16:]
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def _normalize_host(host: str) -> str:
    stripped = (host or "").strip()
    if stripped and stripped not in ("0.0.0.0", "localhost"):
        return stripped
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def discover_gateway(timeout: float = 3.0, port: int = AUREX_DISCOVERY_PORT) -> tuple[str, int] | None:
    """Discover gateway via UDP broadcast."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        probe.settimeout(timeout)
        probe.sendto(AUREX_DISCOVERY_REQUEST.encode("utf-8"), ("255.255.255.255", int(port)))
        payload, _ = probe.recvfrom(1024)
        text = payload.decode("utf-8", errors="ignore").strip()
        if text.startswith("{"):
            data = json.loads(text)
            if data.get("type") == AUREX_DISCOVERY_RESPONSE:
                return str(data.get("ip", "")), int(data.get("port", 0))
            return None
        parts = text.split("|")
        if len(parts) >= 3 and parts[0] == AUREX_DISCOVERY_RESPONSE:
            return parts[1], int(parts[2])
        return None
    except OSError:
        return None
    finally:
        probe.close()


class DiscoveryResponder:
    """Gateway-side UDP responder for AUREX_DISCOVERY_REQUEST probes."""

    def __init__(self, gateway_host: str, gateway_port: int, port: int = AUREX_DISCOVERY_PORT) -> None:
        self.gateway_host = gateway_host
        self.gateway_port = int(gateway_port)
        self.port = int(port)
        self._sock: socket.socket | None = None
        self._running = False

    def serve_forever(self) -> None:
        self._running = True
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("0.0.0.0", self.port))
        self._sock.settimeout(1.0)
        response_obj = {
            "type": AUREX_DISCOVERY_RESPONSE,
            "ip": _normalize_host(self.gateway_host),
            "port": self.gateway_port,
        }
        response_json = json.dumps(response_obj).encode("utf-8")
        while self._running:
            try:
                data, addr = self._sock.recvfrom(1024)
                if data.decode("utf-8", errors="ignore").strip() == AUREX_DISCOVERY_REQUEST:
                    self._sock.sendto(response_json, addr)
            except socket.timeout:
                continue
            except OSError:
                break
        self.close()

    def close(self) -> None:
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


class EncryptedServer:
    """Server-side RSA handshake + AES-CBC transport."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        key_dir: str | Path = "keys",
        key_name: str = "encrypted_server",
        backlog: int = 50,
        timeout: float = 10.0,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.backlog = int(backlog)
        self.timeout = float(timeout)
        self.key_dir = Path(key_dir)
        self.key_name = key_name
        self.private_key = None
        self.public_key_pem = ""
        self._load_or_generate_keys()
        self.server_socket: socket.socket | None = None

    def _load_or_generate_keys(self) -> None:
        self.key_dir.mkdir(parents=True, exist_ok=True)
        private_path = self.key_dir / f"{self.key_name}_private.pem"
        public_path = self.key_dir / f"{self.key_name}_public.pem"
        if private_path.exists() and public_path.exists():
            self.private_key = serialization.load_pem_private_key(
                private_path.read_bytes(),
                password=None,
                backend=default_backend(),
            )
            self.public_key_pem = public_path.read_text(encoding="utf-8")
            return
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048, backend=default_backend())
        public_key = self.private_key.public_key()
        private_path.write_bytes(
            self.private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        self.public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")
        public_path.write_text(self.public_key_pem, encoding="utf-8")

    def bind_and_listen(self) -> None:
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(self.backlog)
        self.server_socket.settimeout(1.0)

    def accept(self) -> tuple[socket.socket, tuple[str, int], bytes]:
        if self.server_socket is None:
            raise RuntimeError("server socket is not listening")
        client, addr = self.server_socket.accept()
        client.settimeout(self.timeout)
        aes_key = self._server_handshake(client)
        return client, addr, aes_key

    def _server_handshake(self, sock: socket.socket) -> bytes:
        if self.private_key is None:
            raise RuntimeError("missing private key")
        _send_frame(sock, self.public_key_pem.encode("utf-8"))
        encrypted_key = _recv_frame(sock)
        aes_key = self.private_key.decrypt(
            encrypted_key,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        if len(aes_key) not in (16, 24, 32):
            raise ValueError("invalid AES key length")
        return aes_key

    def recv_json(self, sock: socket.socket, aes_key: bytes) -> dict[str, Any]:
        encrypted_payload = _recv_frame(sock)
        payload = _aes_decrypt(aes_key, encrypted_payload)
        return json.loads(payload.decode("utf-8"))

    def send_json(self, sock: socket.socket, aes_key: bytes, obj: dict[str, Any]) -> None:
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        encrypted_payload = _aes_encrypt(aes_key, raw)
        _send_frame(sock, encrypted_payload)

    def close(self) -> None:
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except OSError:
                pass
            self.server_socket = None


class EncryptedClient:
    """Client-side RSA handshake + AES-CBC send/recv wrapper."""

    def __init__(self, host: str, port: int, *, timeout: float = 10.0) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self._sock: socket.socket | None = None
        self._aes_key: bytes | None = None

    def connect(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self.timeout)
        self._sock.connect((self.host, self.port))
        public_key_pem = _recv_frame(self._sock).decode("utf-8")
        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"), backend=default_backend())
        self._aes_key = os.urandom(32)
        encrypted_key = public_key.encrypt(
            self._aes_key,
            asym_padding.OAEP(
                mgf=asym_padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        _send_frame(self._sock, encrypted_key)

    def send_json(self, obj: dict[str, Any]) -> None:
        if self._sock is None or self._aes_key is None:
            raise RuntimeError("client is not connected")
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        encrypted_payload = _aes_encrypt(self._aes_key, raw)
        _send_frame(self._sock, encrypted_payload)

    def recv_json(self) -> dict[str, Any]:
        if self._sock is None or self._aes_key is None:
            raise RuntimeError("client is not connected")
        encrypted_payload = _recv_frame(self._sock)
        payload = _aes_decrypt(self._aes_key, encrypted_payload)
        return json.loads(payload.decode("utf-8"))

    def request(self, obj: dict[str, Any], *, expect_response: bool = True) -> dict[str, Any] | None:
        self.connect()
        try:
            self.send_json(obj)
            if expect_response:
                return self.recv_json()
            return None
        finally:
            self.close()

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
            self._aes_key = None
