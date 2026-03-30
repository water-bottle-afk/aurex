from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any, Mapping

from blockchain.key_manager import NodeKeyManager

try:
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
except Exception:  # pragma: no cover - handled at runtime
    ed25519 = None
    serialization = None


_WALLET_DIR = Path(os.getenv("AUREX_WALLET_DIR", Path.home() / ".aurex_wallet"))
_WALLET_FILE = _WALLET_DIR / "wallet_ed25519.json"


def _ensure_wallet_dir() -> None:
    _WALLET_DIR.mkdir(parents=True, exist_ok=True)
    # Use NodeKeyManager as a backend helper to provision the directory.
    # We do not use RSA keys for signing the marketplace protocol.
    try:
        NodeKeyManager("aurex_wallet", key_dir=str(_WALLET_DIR))
    except Exception:
        # Directory exists even if RSA key provisioning fails.
        pass


def _load_or_create_keypair() -> tuple[bytes, bytes]:
    _ensure_wallet_dir()
    if ed25519 is None or serialization is None:
        raise RuntimeError("cryptography is required for Ed25519 signing")

    if _WALLET_FILE.exists():
        payload = json.loads(_WALLET_FILE.read_text(encoding="utf-8"))
        priv_b64 = payload.get("private_key", "")
        pub_b64 = payload.get("public_key", "")
        if priv_b64 and pub_b64:
            return base64.b64decode(priv_b64), base64.b64decode(pub_b64)

    private_key = ed25519.Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_raw = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    _WALLET_FILE.write_text(
        json.dumps(
            {
                "private_key": base64.b64encode(private_raw).decode("ascii"),
                "public_key": base64.b64encode(public_raw).decode("ascii"),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return private_raw, public_raw


def get_public_key_base64() -> str:
    _, public_raw = _load_or_create_keypair()
    return base64.b64encode(public_raw).decode("ascii")


def sign_message(message_bytes: bytes) -> str:
    private_raw, _ = _load_or_create_keypair()
    if ed25519 is None or serialization is None:
        raise RuntimeError("cryptography is required for Ed25519 signing")
    private_key = ed25519.Ed25519PrivateKey.from_private_bytes(private_raw)
    signature = private_key.sign(message_bytes)
    return base64.b64encode(signature).decode("ascii")


def canonical_tx_message(sender: str, data: Mapping[str, Any]) -> bytes:
    payload = {"sender": sender, "data": data}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_tx_id(prefix: str, username: str, asset_id: str | None = None) -> str:
    import secrets
    import time

    now_ms = int(time.time() * 1000)
    rand = secrets.token_hex(4)
    parts = [prefix, username]
    if asset_id:
        parts.append(asset_id)
    parts.extend([str(now_ms), rand])
    raw = "_".join(parts)
    return "".join(ch for ch in raw if ch.isalnum() or ch == "_")
