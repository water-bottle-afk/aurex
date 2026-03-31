"""
Aurex Wallet — Ed25519 key management, local encrypted storage, and signing.

Security model:
  - Private key NEVER leaves this file or the local PEM on disk.
  - Server stores only the public key (base64-encoded raw bytes).
  - Every upload/buy/send action is signed; the server verifies before committing.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import time
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import (
    BestAvailableEncryption,
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


_WALLET_DIR = Path(os.getenv("AUREX_WALLET_DIR", Path.home() / ".aurex_wallet"))
_KEY_FILE = _WALLET_DIR / "aurex_private_key.pem"
_PUB_FILE = _WALLET_DIR / "aurex_public_key.txt"

_KEY_ENV = "AUREX_WALLET_PASSWORD"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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
        pass  # Windows — best-effort


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_user_keys(*, force: bool = False) -> tuple[str, str]:
    """
    Generate a new Ed25519 key pair and save locally.

    Returns:
        (public_key_base64, key_file_path)  — the private key path for user info.

    The private key is saved as an encrypted PEM file (password from
    AUREX_WALLET_PASSWORD env var, or unencrypted if env var not set).

    Prints a prominent warning reminding the user to back up the key file.
    """
    _WALLET_DIR.mkdir(parents=True, exist_ok=True)

    if _KEY_FILE.exists() and not force:
        return get_public_key_base64(), str(_KEY_FILE)

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()

    password = _wallet_password()
    pem_bytes = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=_encryption_algorithm(password),
    )
    _KEY_FILE.write_bytes(pem_bytes)
    _set_private_permissions(_KEY_FILE)

    pub_raw = public_key.public_bytes(encoding=Encoding.Raw, format=PublicFormat.Raw)
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    _PUB_FILE.write_text(pub_b64 + "\n", encoding="utf-8")

    print(
        "\n"
        "╔══════════════════════════════════════════════════════════╗\n"
        "║  KEY GENERATED — CRITICAL SECURITY NOTICE               ║\n"
        "║                                                          ║\n"
        f"║  Private key saved to: {str(_KEY_FILE)[:34]:<34} ║\n"
        "║                                                          ║\n"
        "║  ⚠  BACK UP THIS FILE NOW.                              ║\n"
        "║  If lost, your Aurex assets are UNRECOVERABLE.          ║\n"
        "╚══════════════════════════════════════════════════════════╝\n"
    )
    return pub_b64, str(_KEY_FILE)


def _load_private_key() -> ed25519.Ed25519PrivateKey:
    """Load private key from PEM file, decrypting with env password if needed."""
    if not _KEY_FILE.exists():
        generate_user_keys()
    pem_bytes = _KEY_FILE.read_bytes()
    password = _wallet_password()
    return serialization.load_pem_private_key(pem_bytes, password=password)


def get_public_key_base64() -> str:
    """Return the base64-encoded raw public key bytes (32 bytes for Ed25519)."""
    if _PUB_FILE.exists():
        return _PUB_FILE.read_text(encoding="utf-8").strip()
    private_key = _load_private_key()
    pub_raw = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    _WALLET_DIR.mkdir(parents=True, exist_ok=True)
    _PUB_FILE.write_text(pub_b64 + "\n", encoding="utf-8")
    return pub_b64


def sign_message(message_bytes: bytes) -> str:
    """Sign arbitrary bytes with the local Ed25519 private key.

    Returns base64-encoded signature string.
    """
    private_key = _load_private_key()
    signature = private_key.sign(message_bytes)
    return base64.b64encode(signature).decode("ascii")


def verify_message(public_key_b64: str, message_bytes: bytes, signature_b64: str) -> bool:
    """Verify a signature using a raw-bytes base64 public key.

    Returns True if valid, False otherwise.
    """
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
