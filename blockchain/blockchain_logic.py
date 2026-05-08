"""Core blockchain and state logic for Aurex modular node/gateway flow."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import pickle

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils


def canonical_json(data: dict[str, Any]) -> bytes:
    """Deterministic JSON bytes for hashing/signature verification."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def verify_transaction_signature(public_key_pem: str, payload: dict[str, Any], signature_b64: str) -> bool:
    """
    Verify ECDSA signature over hash(payload).
    Transactions must never include private keys.
    """
    if not public_key_pem or not signature_b64 or not isinstance(payload, dict):
        return False
    if "private_key" in payload:
        return False
    digest = hashlib.sha256(canonical_json(payload)).digest()
    try:
        signature = base64.b64decode(signature_b64.encode("utf-8"))
        public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"), backend=default_backend())
        if not isinstance(public_key, ec.EllipticCurvePublicKey):
            return False
        public_key.verify(signature, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        return True
    except Exception:
        return False


@dataclass
class SignedTransaction:
    """Protocol-level signed transaction."""

    payload: dict[str, Any]
    public_key: str
    signature: str
    tx_type: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tx_type": self.tx_type,
            "payload": self.payload,
            "public_key": self.public_key,
            "signature": self.signature,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SignedTransaction":
        return cls(
            payload=dict(raw.get("payload") or {}),
            public_key=str(raw.get("public_key") or ""),
            signature=str(raw.get("signature") or ""),
            tx_type=str(raw.get("tx_type") or ""),
            timestamp=float(raw.get("timestamp") or time.time()),
        )

    def is_valid(self) -> bool:
        return verify_transaction_signature(self.public_key, self.payload, self.signature)


@dataclass
class Block:
    index: int
    prev_hash: str
    nonce: int
    timestamp: float
    transactions: list[dict[str, Any]]
    hash: str = ""

    def compute_hash(self) -> str:
        data = {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
        }
        return hashlib.sha256(canonical_json(data)).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "prev_hash": self.prev_hash,
            "nonce": self.nonce,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Block":
        return cls(
            index=int(raw.get("index", 0)),
            prev_hash=str(raw.get("prev_hash", "0")),
            nonce=int(raw.get("nonce", 0)),
            timestamp=float(raw.get("timestamp", time.time())),
            transactions=list(raw.get("transactions") or []),
            hash=str(raw.get("hash") or ""),
        )


class StateStore:
    """Balance state persisted as pickle. key=User_Public_Key value=Balance."""

    def __init__(self, state_path: str | Path) -> None:
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state: dict[str, float] = {}
        self.load()

    def load(self) -> None:
        if not self.state_path.exists():
            self.state = {}
            return
        try:
            with self.state_path.open("rb") as handle:
                raw = pickle.load(handle)
            self.state = dict(raw or {})
        except Exception:
            self.state = {}

    def save(self) -> None:
        with self.state_path.open("wb") as handle:
            pickle.dump(self.state, handle)

    def get(self, public_key: str) -> float:
        return float(self.state.get(public_key, 0.0))

    def set(self, public_key: str, value: float) -> None:
        self.state[public_key] = float(value)

    def apply_transaction(self, tx: SignedTransaction) -> tuple[bool, str]:
        if not tx.is_valid():
            return False, "invalid signature"
        payload = tx.payload
        sender = str(payload.get("from") or payload.get("sender") or "")
        receiver = str(payload.get("to") or payload.get("receiver") or "")
        amount_raw = payload.get("amount", 0)
        try:
            amount = float(amount_raw)
        except Exception:
            return False, "invalid amount"
        action = str(payload.get("action") or tx.tx_type or "").upper()

        if action in ("MINT", "ASSET_MINT"):
            owner = str(payload.get("owner") or sender or tx.public_key)
            if not owner:
                return False, "mint missing owner"
            if owner not in self.state:
                self.state[owner] = 0.0
            return True, "ok"

        if action in ("TRANSFER", "ASSET_TRANSFER", "ASSET_PURCHASE", "BUY", "TRADE"):
            if not sender or not receiver:
                return False, "transfer missing sender/receiver"
            if amount < 0:
                return False, "negative amount"
            if self.get(sender) < amount:
                return False, "insufficient balance"
            self.set(sender, self.get(sender) - amount)
            self.set(receiver, self.get(receiver) + amount)
            return True, "ok"

        return False, f"unsupported tx action {action}"


class BlockchainEngine:
    """JSON ledger + pickle user state with PoW validation/sync helpers."""

    def __init__(self, ledger_path: str | Path, state_path: str | Path, *, difficulty: int = 3) -> None:
        self.ledger_path = Path(ledger_path)
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_store = StateStore(state_path)
        self.difficulty = int(difficulty)
        self.chain: list[Block] = []
        self.pending_transactions: list[SignedTransaction] = []
        self._load_chain()
        if not self.chain:
            self._create_genesis()

    def _create_genesis(self) -> None:
        genesis = Block(index=0, prev_hash="0", nonce=0, timestamp=time.time(), transactions=[], hash="")
        genesis.hash = genesis.compute_hash()
        self.chain = [genesis]
        self._save_chain()

    def _load_chain(self) -> None:
        if not self.ledger_path.exists():
            self.chain = []
            return
        try:
            raw = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            self.chain = [Block.from_dict(item) for item in (raw or [])]
        except Exception:
            self.chain = []

    def _save_chain(self) -> None:
        payload = [block.to_dict() for block in self.chain]
        self.ledger_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def ledger_length(self) -> int:
        return len(self.chain)

    @property
    def latest_block(self) -> Block:
        return self.chain[-1]

    def add_transaction(self, tx: SignedTransaction) -> tuple[bool, str]:
        if not tx.is_valid():
            return False, "invalid signature"
        self.pending_transactions.append(tx)
        return True, "queued"

    def _pow_target(self) -> str:
        return "0" * self.difficulty

    def mine_pending_block(self) -> Block | None:
        if not self.pending_transactions:
            return None
        prev = self.latest_block
        tx_payloads = [tx.to_dict() for tx in self.pending_transactions]
        block = Block(
            index=prev.index + 1,
            prev_hash=prev.hash,
            nonce=0,
            timestamp=time.time(),
            transactions=tx_payloads,
            hash="",
        )
        target = self._pow_target()
        while True:
            digest = block.compute_hash()
            if digest.startswith(target):
                block.hash = digest
                return block
            block.nonce += 1

    def validate_block(self, block: Block) -> tuple[bool, str]:
        expected_index = self.latest_block.index + 1
        if block.index != expected_index:
            return False, "bad index"
        if block.prev_hash != self.latest_block.hash:
            return False, "bad prev_hash"
        digest = block.compute_hash()
        if digest != block.hash:
            return False, "bad hash"
        if not digest.startswith(self._pow_target()):
            return False, "pow target not reached"

        # State validation on a snapshot before commit.
        snapshot = dict(self.state_store.state)
        temp_store = StateStore(self.state_store.state_path)
        temp_store.state = snapshot
        for raw_tx in block.transactions:
            signed = SignedTransaction.from_dict(raw_tx)
            ok, reason = temp_store.apply_transaction(signed)
            if not ok:
                return False, f"tx invalid: {reason}"
        return True, "ok"

    def add_block(self, block: Block) -> tuple[bool, str]:
        ok, reason = self.validate_block(block)
        if not ok:
            return False, reason
        for raw_tx in block.transactions:
            signed = SignedTransaction.from_dict(raw_tx)
            tx_ok, tx_reason = self.state_store.apply_transaction(signed)
            if not tx_ok:
                return False, tx_reason
        self.chain.append(block)
        self.pending_transactions.clear()
        self._save_chain()
        self.state_store.save()
        return True, "committed"

    def export_ledger(self) -> list[dict[str, Any]]:
        return [block.to_dict() for block in self.chain]

    def import_full_ledger(self, chain_data: list[dict[str, Any]], state_data: dict[str, float]) -> tuple[bool, str]:
        if not isinstance(chain_data, list):
            return False, "chain_data must be list"
        new_chain = [Block.from_dict(entry) for entry in chain_data]
        if not new_chain:
            return False, "empty chain"

        # Full-chain validation.
        for idx, block in enumerate(new_chain):
            if idx == 0:
                if block.hash != block.compute_hash():
                    return False, "bad genesis"
                continue
            prev = new_chain[idx - 1]
            if block.index != prev.index + 1:
                return False, "non-sequential index"
            if block.prev_hash != prev.hash:
                return False, "broken prev hash link"
            if block.compute_hash() != block.hash:
                return False, "hash mismatch in chain"

        self.chain = new_chain
        self._save_chain()
        self.state_store.state = dict(state_data or {})
        self.state_store.save()
        self.pending_transactions.clear()
        return True, "synced"
