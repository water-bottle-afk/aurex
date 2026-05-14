"""RSA + AES-CBC socket helpers for Aurex node<->gateway secure channel."""

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

MAX_FRAME_SIZE = 16 * 1024 * 1024
IV_SIZE = 16


def build_proto_message(msg_type: str, payload: dict[str, Any], signature: str | None = None) -> dict[str, Any]:
    """Build canonical proto envelope: {'type', 'payload', 'signature?'}."""
    message: dict[str, Any] = {"type": str(msg_type), "payload": payload if isinstance(payload, dict) else {}}
    if signature:
        message["signature"] = signature
    return message


def validate_proto_message(raw: dict[str, Any]) -> tuple[bool, str]:
    """Validate minimal proto schema."""
    if not isinstance(raw, dict):
        return False, "message must be object"
    if "type" not in raw:
        return False, "missing type"
    if "payload" not in raw:
        return False, "missing payload"
    if not isinstance(raw.get("type"), str) or not raw.get("type"):
        return False, "type must be non-empty string"
    if not isinstance(raw.get("payload"), dict):
        return False, "payload must be object"
    if "signature" in raw and raw["signature"] is not None and not isinstance(raw["signature"], str):
        return False, "signature must be string"
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


def _aes_encrypt_iv_tail(aes_key: bytes, plaintext: bytes) -> bytes:
    """Encrypt bytes with AES-CBC and append IV at the end (ciphertext || iv)."""
    iv = os.urandom(IV_SIZE)
    padder = sym_padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return ciphertext + iv


def _aes_decrypt_iv_tail(aes_key: bytes, encrypted: bytes) -> bytes:
    """Decrypt payload where trailing fixed-size bytes hold IV."""
    if len(encrypted) <= IV_SIZE:
        raise ValueError("encrypted payload too short")
    iv = encrypted[-IV_SIZE:]
    ciphertext = encrypted[:-IV_SIZE]
    cipher = Cipher(algorithms.AES(aes_key), modes.CBC(iv), backend=default_backend())
    decryptor = cipher.decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = sym_padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


class EncryptedServer:
    """Server wrapper: RSA handshake then AES-CBC transport (IV appended to message tail)."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        key_dir: str | Path = "keys",
        key_name: str = "aurex_secure_server",
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
        self.server_socket: socket.socket | None = None
        self._load_or_generate_keys()

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
        aes_key = self._handshake(client)
        return client, addr, aes_key

    def _handshake(self, sock: socket.socket) -> bytes:
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
        raw = _aes_decrypt_iv_tail(aes_key, encrypted_payload)
        return json.loads(raw.decode("utf-8"))

    def send_json(self, sock: socket.socket, aes_key: bytes, obj: dict[str, Any]) -> None:
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        encrypted_payload = _aes_encrypt_iv_tail(aes_key, raw)
        _send_frame(sock, encrypted_payload)

    def close(self) -> None:
        if self.server_socket is not None:
            try:
                self.server_socket.close()
            except OSError:
                pass
            self.server_socket = None


class EncryptedClient:
    """Client wrapper for RSA bootstrap + AES-CBC channel with tail IV."""

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
        encrypted_payload = _aes_encrypt_iv_tail(self._aes_key, raw)
        _send_frame(self._sock, encrypted_payload)

    def recv_json(self) -> dict[str, Any]:
        if self._sock is None or self._aes_key is None:
            raise RuntimeError("client is not connected")
        encrypted_payload = _recv_frame(self._sock)
        raw = _aes_decrypt_iv_tail(self._aes_key, encrypted_payload)
        return json.loads(raw.decode("utf-8"))

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


def send_secure_request(
    host: str,
    port: int,
    message: dict[str, Any],
    *,
    timeout: float = 10.0,
    expect_response: bool = True,
) -> dict[str, Any] | None:
    """One-shot helper for secure request/response."""
    return EncryptedClient(host, port, timeout=timeout).request(message, expect_response=expect_response)
