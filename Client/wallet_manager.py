"""Client-side Aurex wallet management (ECDSA secp256k1, hex keys, local-only private key)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _private_key_from_hex(private_key_hex: str) -> ec.EllipticCurvePrivateKey:
    value = int(private_key_hex, 16)
    return ec.derive_private_key(value, ec.SECP256K1())


def _public_key_hex_from_private(private_key: ec.EllipticCurvePrivateKey) -> str:
    public_key = private_key.public_key()
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return raw.hex()


def _public_key_from_hex(public_key_hex: str) -> ec.EllipticCurvePublicKey:
    return ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(public_key_hex))


@dataclass
class WalletData:
    username: str
    public_key: str
    private_key: str

    def to_dict(self) -> dict[str, str]:
        return {
            "username": self.username,
            "public_key": self.public_key,
            "private_key": self.private_key,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "WalletData":
        return cls(
            username=str(raw.get("username", "")).strip(),
            public_key=str(raw.get("public_key", "")).strip(),
            private_key=str(raw.get("private_key", "")).strip(),
        )

    def validate(self) -> tuple[bool, str]:
        if not self.username:
            return False, "wallet username is missing"
        if not self.public_key or not self.private_key:
            return False, "wallet keys are missing"
        try:
            private_key = _private_key_from_hex(self.private_key)
            expected_public = _public_key_hex_from_private(private_key)
        except Exception:
            return False, "invalid private key format"
        if expected_public.lower() != self.public_key.lower():
            return False, "public key does not match private key"
        return True, "ok"

    def sign_payload(self, payload: dict[str, Any]) -> str:
        private_key = _private_key_from_hex(self.private_key)
        signature = private_key.sign(_canonical_json_bytes(payload), ec.ECDSA(hashes.SHA256()))
        return signature.hex()

    def verify_signature(self, payload: dict[str, Any], signature_hex: str) -> bool:
        try:
            public_key = _public_key_from_hex(self.public_key)
            public_key.verify(bytes.fromhex(signature_hex), _canonical_json_bytes(payload), ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError):
            return False


class WalletManager:
    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir if base_dir else Path(__file__).resolve().parent
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def wallet_path_for_user(self, username: str) -> Path:
        user_dir = self.base_dir / username
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir / "wallet.json"

    def _legacy_wallet_path(self, username: str) -> Path:
        return self.base_dir / "wallets" / username / "wallet.json"

    def generate_wallet(self, username: str) -> WalletData:
        private_key = ec.generate_private_key(ec.SECP256K1())
        private_numbers = private_key.private_numbers().private_value
        private_hex = private_numbers.to_bytes(32, "big").hex()
        public_hex = _public_key_hex_from_private(private_key)
        wallet = WalletData(username=username, public_key=public_hex, private_key=private_hex)
        self.save_wallet(wallet, self.wallet_path_for_user(username))
        return wallet

    def save_wallet(self, wallet: WalletData, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(wallet.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def load_wallet_from_path(self, path: Path) -> WalletData:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("wallet file must be a JSON object")
        expected = {"username", "public_key", "private_key"}
        actual = set(raw.keys())
        if actual != expected:
            raise ValueError("wallet must contain exactly: username, public_key, private_key")
        wallet = WalletData.from_dict(raw)
        ok, reason = wallet.validate()
        if not ok:
            raise ValueError(reason)
        return wallet

    def load_wallet_for_user(self, username: str) -> WalletData | None:
        path = self.wallet_path_for_user(username)
        if not path.exists():
            legacy = self._legacy_wallet_path(username)
            if legacy.exists():
                wallet = self.load_wallet_from_path(legacy)
                self.save_wallet(wallet, path)
                return wallet
            return None
        return self.load_wallet_from_path(path)
