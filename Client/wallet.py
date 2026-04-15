"""
Aurex Wallet - Ed25519 key management, local encrypted storage, and signing.

Security model:
  - Private key NEVER leaves this file or the local PEM on disk.
  - Server stores only the public key (base64-encoded raw bytes).
  - Every upload/buy/send action is signed; the server verifies before committing.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def _default_wallet_dir() -> Path:
    """Resolve wallet dir: env override -> ~/Downloads/aurex_wallet -> ~/.aurex_wallet."""
    env = os.getenv("AUREX_WALLET_DIR")
    if env:
        return Path(env)
    downloads = Path.home() / "Downloads" / "aurex_wallet"
    try:
        downloads.mkdir(parents=True, exist_ok=True)
        return downloads
    except Exception:
        return Path.home() / ".aurex_wallet"


_WALLET_DIR = _default_wallet_dir()
_KEY_FILE = _WALLET_DIR / "aurex_private_key.pem"
_PUB_FILE = _WALLET_DIR / "aurex_public_key.txt"

_KEY_ENV = "AUREX_WALLET_PASSWORD"
_ACTIVE_USER: str | None = None


def _wallet_password() -> bytes | None:
    """Return wallet encryption password from env, or None for no encryption."""
    pw = os.environ.get(_KEY_ENV, "")
    return pw.encode("utf-8") if pw else None


def _encryption_algorithm(password: bytes | None):
    if password:
        return BestAvailableEncryption(password)
    return NoEncryption()


def _set_private_permissions(path: Path) -> None:
    """Restrict key file to owner read/write only (0600) on Unix."""
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except NotImplementedError:
        pass


def _safe_user_fragment(username: str | None) -> str | None:
    if not username:
        return None
    cleaned = "".join(ch for ch in username.strip() if ch.isalnum() or ch in ("_", "-"))
    return cleaned or None


def get_key_file_path(username: str | None = None) -> Path:
    user_fragment = _safe_user_fragment(username or _ACTIVE_USER)
    if not user_fragment:
        return _KEY_FILE
    return _WALLET_DIR / user_fragment / "aurex_private_key.pem"


def get_public_key_file_path(username: str | None = None) -> Path:
    user_fragment = _safe_user_fragment(username or _ACTIVE_USER)
    if not user_fragment:
        return _PUB_FILE
    return _WALLET_DIR / user_fragment / "aurex_public_key.txt"


def activate_wallet_user(username: str, *, password: str | None = None, ensure_keys: bool = False) -> None:
    global _ACTIVE_USER
    _ACTIVE_USER = _safe_user_fragment(username)
    if ensure_keys and _ACTIVE_USER and not get_key_file_path().exists():
        generate_user_keys(username=username, password_material=password, force=True)


def _derive_private_key(username: str, password_material: str) -> ed25519.Ed25519PrivateKey:
    password_hash = hashlib.sha256(password_material.encode("utf-8")).hexdigest()
    seed = hashlib.sha256(f"{username}|{password_hash}".encode("utf-8")).digest()
    return ed25519.Ed25519PrivateKey.from_private_bytes(seed)


def generate_user_keys(
    *,
    username: str | None = None,
    password_material: str | None = None,
    force: bool = False,
) -> tuple[str, str]:
    """
    Generate a user key pair and save locally.

    When username and password are provided, the Ed25519 private key is derived
    deterministically from username + hashed password so different users do not
    share a wallet even if they reuse the same plaintext password.
    """
    key_file = get_key_file_path(username)
    pub_file = get_public_key_file_path(username)
    key_file.parent.mkdir(parents=True, exist_ok=True)

    if key_file.exists() and not force:
        return get_public_key_base64(username=username), str(key_file)

    resolved_username = username or _ACTIVE_USER
    if resolved_username and password_material:
        private_key = _derive_private_key(resolved_username, password_material)
    else:
        private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    password = _wallet_password()
    pem_bytes = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=_encryption_algorithm(password),
    )
    key_file.write_bytes(pem_bytes)
    _set_private_permissions(key_file)

    pub_raw = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    pub_file.write_text(pub_b64 + "\n", encoding="utf-8")

    print(
        "\n"
        "============================================================\n"
        "  KEY GENERATED - CRITICAL SECURITY NOTICE\n"
        f"  Private key saved to: {str(key_file)}\n"
        "  Back up this file now.\n"
        "============================================================\n"
    )
    return pub_b64, str(key_file)


def _load_private_key(username: str | None = None) -> ed25519.Ed25519PrivateKey:
    """Load private key from PEM file, decrypting with env password if needed."""
    key_file = get_key_file_path(username)
    if not key_file.exists():
        generate_user_keys(username=username)
    pem_bytes = key_file.read_bytes()
    password = _wallet_password()
    return serialization.load_pem_private_key(pem_bytes, password=password)


def get_public_key_base64(username: str | None = None) -> str:
    """Return the base64-encoded raw public key bytes (32 bytes for Ed25519)."""
    pub_file = get_public_key_file_path(username)
    if pub_file.exists():
        return pub_file.read_text(encoding="utf-8").strip()
    private_key = _load_private_key(username)
    pub_raw = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    pub_file.parent.mkdir(parents=True, exist_ok=True)
    pub_file.write_text(pub_b64 + "\n", encoding="utf-8")
    return pub_b64


def sign_message(message_bytes: bytes, username: str | None = None) -> str:
    """Sign arbitrary bytes with the local Ed25519 private key."""
    private_key = _load_private_key(username)
    signature = private_key.sign(message_bytes)
    return base64.b64encode(signature).decode("ascii")


def verify_message(public_key_b64: str, message_bytes: bytes, signature_b64: str) -> bool:
    """Verify a signature using a raw-bytes base64 public key."""
    try:
        pub_raw = base64.b64decode(public_key_b64.encode("ascii"))
        sig_raw = base64.b64decode(signature_b64.encode("ascii"))
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(pub_raw)
        public_key.verify(sig_raw, message_bytes)
        return True
    except Exception:
        return False


def canonical_tx_message(sender: str, data: Mapping[str, Any]) -> bytes:
    """Produce a deterministic canonical JSON byte string for signing."""
    payload = {"sender": sender, "data": data}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_tx_id(prefix: str, username: str, asset_id: str | None = None) -> str:
    """Generate a unique transaction ID with a timestamp and random suffix."""
    now_ms = int(time.time() * 1000)
    rand = secrets.token_hex(4)
    parts = [prefix, username]
    if asset_id:
        parts.append(asset_id)
    parts.extend([str(now_ms), rand])
    raw = "_".join(parts)
    return "".join(ch for ch in raw if ch.isalnum() or ch == "_")
