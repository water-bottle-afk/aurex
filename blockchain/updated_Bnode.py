__author__ = "Nadav"

import argparse
import base64
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any

# Adds the root folder to enable imports from SharedResources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SharedResources.classes import RSA_Client, RSA_Server, UDPClient
from SharedResources.config import GATEWAY_UDP_PORT
from SharedResources.logging import Logger


class BlockchainNode:
    """Single-file blockchain node runtime with gateway relay + peer ledger sync."""

    CHUNK_SIZE = 8192

    def __init__(self, ip: str, port: int, difficulty: int = 2, symbol: str = "A"):
        self.ip = str(ip)
        self.port = int(port)
        self.difficulty = int(difficulty)
        self.symbol = symbol
        self.node_id = f"node_{self.ip}_{self.port}"

        self.logger = Logger("updated_Bnode")
        self.Print = lambda *args: self.logger.info(" ".join(str(a) for a in args))

        # Node local storage per node_<ip>_<port>/
        self.base_dir = Path(__file__).resolve().parent
        self.node_dir = self.base_dir / self.node_id
        self.node_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.node_dir / "ledger.json"
        self.balances_path = self.node_dir / "balances.json"

        self.lock = threading.RLock()
        self.stop_event = threading.Event()

        self.chain: list[dict[str, Any]] = []
        self.balances: dict[str, float] = {}
        self.pending_txs: list[dict[str, Any]] = []

        self.gateway_client: RSA_Client | None = None
        self.gateway_comm = None

        self.server_for_peers = RSA_Server(
            self.ip,
            self.port,
            dir_for_keys=str(self.node_dir / "NodeKeys"),
            name=f"NodePeerServer_{self.port}",
        )
        self.server_for_peers.handle_client = self.handle_peer_connection

        self._load_local_state()

    # -------- lifecycle --------

    def start(self):
        self.connect_to_gateway()
        threading.Thread(target=self.server_for_peers.start, daemon=True).start()
        self.Print(f"[{self.node_id}] listening for peers at {self.ip}:{self.port}")
        while not self.stop_event.is_set():
            time.sleep(0.2)

    def stop(self):
        self.stop_event.set()

    def connect_to_gateway(self):
        udp = UDPClient(GATEWAY_UDP_PORT)
        gw_ip, gw_port = udp.run()

        client = RSA_Client(gw_ip, gw_port, name=f"{self.node_id}_to_gateway")
        client.sock.connect((gw_ip, gw_port))
        client.contact_with_RSA()

        self.gateway_client = client
        self.gateway_comm = client.communication

        threading.Thread(target=self._listen_gateway_loop, daemon=True).start()
        self.register_blockchain_node()
        self.Print(f"[{self.node_id}] connected to gateway at {gw_ip}:{gw_port}")

    def _listen_gateway_loop(self):
        while not self.stop_event.is_set() and self.gateway_comm is not None:
            msg = self.gateway_comm.recv_one_message()
            if not msg:
                break
            self._handle_gateway_message(msg)

    # -------- local json persistence --------

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return default

    def _save_json(self, path: Path, data):
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_local_state(self):
        with self.lock:
            ledger = self._load_json(self.ledger_path, [])
            balances = self._load_json(self.balances_path, {})
            self.chain = ledger if isinstance(ledger, list) else []
            self.balances = balances if isinstance(balances, dict) else {}
            self._save_json(self.ledger_path, self.chain)
            self._save_json(self.balances_path, self.balances)

    def _persist_local_state(self):
        with self.lock:
            self._save_json(self.ledger_path, self.chain)
            self._save_json(self.balances_path, self.balances)

    # -------- blockchain logic --------

    def get_balance(self, userpk: str) -> float:
        with self.lock:
            return float(self.balances.get(userpk, 0.0))

    def _last_hash(self) -> str:
        if not self.chain:
            return "0" * 64
        return str(self.chain[-1].get("hash", "0" * 64))

    def _block_hash(self, block: dict[str, Any]) -> str:
        content = json.dumps(block, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def validate_tx(self, tx: dict[str, Any]):
        sender = str(tx.get("sender", ""))
        amount = float(tx.get("amount", 0.0))
        if amount < 0:
            return False
        if sender and self.get_balance(sender) < amount:
            return False
        return True

    def mine(self, transaction: dict[str, Any]):
        if not self.validate_tx(transaction):
            return None

        new_block = {
            "index": len(self.chain),
            "prev_hash": self._last_hash(),
            "timestamp": time.time(),
            "tx": transaction,
            "public_key": str(transaction.get("public_key", "")),
            "signature": str(transaction.get("signature", "")),
            "nonce": 0,
            "difficulty": self.difficulty,
            "symbol": self.symbol,
        }
        target = "0" * self.difficulty
        while not self.stop_event.is_set():
            digest = self._block_hash(new_block)
            if digest.startswith(target):
                new_block["hash"] = digest
                break
            new_block["nonce"] += 1

        if "hash" not in new_block:
            return None
        self.add_block(new_block)
        return new_block

    def add_block(self, block: dict[str, Any]):
        tx = block.get("tx", {}) if isinstance(block.get("tx"), dict) else {}
        if not tx and isinstance(block.get("transaction"), dict):
            tx = block.get("transaction")
        tx_data = tx.get("data") if isinstance(tx.get("data"), dict) else tx
        sender = str(tx_data.get("sender", tx.get("sender", "")))
        receiver = str(tx_data.get("receiver", tx.get("receiver", "")))
        amount = float(tx_data.get("amount", tx.get("amount", 0.0)))

        with self.lock:
            if sender:
                self.balances[sender] = round(float(self.balances.get(sender, 0.0)) - amount, 8)
            if receiver:
                self.balances[receiver] = round(float(self.balances.get(receiver, 0.0)) + amount, 8)

            self.chain.append(block)
            self.pending_txs = []
            self._persist_local_state()
            self.register_blockchain_node()

    # -------- gateway communication --------

    def _send_gateway(self, msg: dict[str, Any]):
        if not self.gateway_comm:
            return
        try:
            self.gateway_comm.send_one_message(msg)
        except Exception as exc:
            self.Print(f"[{self.node_id}] gateway send failed: {exc}")

    def register_blockchain_node(self):
        self._send_gateway(
            {
                "type": "register_blockchain_node",
                "data": {"ip": self.ip, "port": self.port, "chain_length": len(self.chain)},
                "sender_ip": self.ip,
                "sender_port": self.port,
            }
        )

    def notify_gateway(self, block: dict[str, Any]):
        self._send_gateway(
            {
                "type": "broadcast_tx_to_verify",
                "data": {
                    "block": block,
                    "publisher_chain_length": len(self.chain),
                },
                "sender_ip": self.ip,
                "sender_port": self.port,
            }
        )

    def notify_buy_success(self, tx_data: dict[str, Any]):
        self._send_gateway(
            {
                "type": "buy_success",
                "data": tx_data,
                "sender_ip": self.ip,
                "sender_port": self.port,
            }
        )

    def notify_sell_success(self, tx_data: dict[str, Any]):
        self._send_gateway(
            {
                "type": "sell_success",
                "data": tx_data,
                "sender_ip": self.ip,
                "sender_port": self.port,
            }
        )

    def send_balance(self, userpk: str):
        self._send_gateway(
            {
                "type": "send_balance",
                "userpk": userpk,
                "data": {"userpk": userpk, "balance": self.get_balance(userpk)},
                "sender_ip": self.ip,
                "sender_port": self.port,
            }
        )

    def _handle_gateway_message(self, msg: dict[str, Any]):
        msg_type = str(msg.get("type", "")).strip().lower()

        if msg_type == "tx_request_buy":
            self.handle_tx_request_buy(msg)
            return
        if msg_type == "tx_request_sell":
            self.handle_tx_request_sell(msg)
            return
        if msg_type == "broadcast_tx_to_verify":
            self.handle_broadcast_tx_to_verify(msg)
            return
        if msg_type == "get_ledger":
            self.handle_get_ledger_sync(msg)
            return
        if msg_type in {"handle_get_balance", "get_balance"}:
            if msg.get("publisher_ip") and msg.get("publisher_port"):
                self.handle_get_balance_sync(msg)
                return
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            userpk = msg.get("userpk") or data.get("userpk")
            if userpk:
                self.send_balance(str(userpk))
            return

    def _tx_from_gateway_message(self, msg: dict[str, Any], tx_type: str):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        payload = data.get("data") if isinstance(data.get("data"), dict) else data

        tx = {
            "type": tx_type,
            "tx_id": payload.get("tx_id") or f"{tx_type}-{int(time.time() * 1000)}",
            "sender": str(payload.get("sender") or payload.get("buyer") or ""),
            "receiver": str(payload.get("receiver") or payload.get("seller") or ""),
            "amount": float(payload.get("amount") or payload.get("price") or 0.0),
            "asset_id": payload.get("asset_id"),
            "timestamp": payload.get("timestamp") or time.time(),
            "data": payload.get("data") if isinstance(payload.get("data"), dict) else payload,
            "signature": str(payload.get("signature", "")),
            "public_key": str(payload.get("public_key", "")),
        }
        return tx

    def handle_tx_request_buy(self, msg: dict[str, Any]):
        tx = self._tx_from_gateway_message(msg, "BUY")
        self.pending_txs.append(tx)
        block = self.mine(tx)
        if block is not None:
            self.notify_buy_success(tx)
            self.notify_gateway(block)

    def handle_tx_request_sell(self, msg: dict[str, Any]):
        tx = self._tx_from_gateway_message(msg, "SELL")
        self.pending_txs.append(tx)
        block = self.mine(tx)
        if block is not None:
            self.notify_sell_success(tx)
            self.notify_gateway(block)

    def handle_broadcast_tx_to_verify(self, msg: dict[str, Any]):
        sender_ip = str(msg.get("sender_ip") or "")
        sender_port = int(msg.get("sender_port") or 0)
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        publisher_chain_length = int(data.get("publisher_chain_length") or 0)
        if publisher_chain_length > len(self.chain) + 1:
            self.ensure_local_state_or_fetch(sender_ip, sender_port, publisher_chain_length, str(data.get("userpk") or ""))
            return
        block = data.get("block") if isinstance(data.get("block"), dict) else {}
        if block and int(block.get("index", -1)) == len(self.chain) and str(block.get("prev_hash", "")) == self._last_hash():
            self.add_block(block)

    # -------- peer ledger sharing --------

    def ensure_local_state_or_fetch(self, publisher_ip: str, publisher_port: int, publisher_chain_length: int = 0, userpk: str = ""):
        if not publisher_ip or not publisher_port:
            return
        ledger_missing = (not self.ledger_path.exists()) or (self.ledger_path.stat().st_size == 0)
        balances_missing = (not self.balances_path.exists()) or (self.balances_path.stat().st_size == 0)
        lagging = publisher_chain_length > len(self.chain) + 1
        if ledger_missing or balances_missing or lagging:
            self.request_ledger_from_peer(publisher_ip, publisher_port)
            if userpk:
                self.request_balance_from_peer(publisher_ip, publisher_port, userpk)
            self.register_blockchain_node()

    def handle_get_ledger_sync(self, msg: dict[str, Any]):
        publisher_ip = str(msg.get("publisher_ip") or "")
        publisher_port = int(msg.get("publisher_port") or 0)
        publisher_chain_length = int(msg.get("publisher_chain_length") or 0)
        self.ensure_local_state_or_fetch(publisher_ip, publisher_port, publisher_chain_length, "")

    def handle_get_balance_sync(self, msg: dict[str, Any]):
        publisher_ip = str(msg.get("publisher_ip") or "")
        publisher_port = int(msg.get("publisher_port") or 0)
        userpk = str(msg.get("userpk") or "")
        if publisher_ip and publisher_port and userpk:
            self.request_balance_from_peer(publisher_ip, publisher_port, userpk)

    def handle_peer_connection(self, comm):
        while True:
            msg = comm.recv_one_message()
            if not msg:
                break
            msg_type = str(msg.get("type", "")).strip().upper()
            if msg_type == "GET_LEDGER":
                self._send_ledger_snapshot(comm)
            elif msg_type == "GET_BALANCE":
                userpk = str(msg.get("userpk") or "")
                comm.send_one_message(
                    {
                        "type": "BALANCE_RESPONSE",
                        "userpk": userpk,
                        "balance": self.get_balance(userpk),
                    }
                )

    def _send_ledger_snapshot(self, comm):
        snapshot = {
            "ledger": self.chain,
            "balances": self.balances,
            "publisher": {"ip": self.ip, "port": self.port, "node_id": self.node_id},
        }
        raw = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
        chunks = [raw[i : i + self.CHUNK_SIZE] for i in range(0, len(raw), self.CHUNK_SIZE)]

        comm.send_one_message(
            {
                "type": "LEDGER_SNAPSHOT_START",
                "chunks": len(chunks),
                "total_bytes": len(raw),
            }
        )

        for idx, chunk in enumerate(chunks):
            comm.send_one_message(
                {
                    "type": "LEDGER_SNAPSHOT_CHUNK",
                    "index": idx,
                    "data_b64": base64.b64encode(chunk).decode("ascii"),
                }
            )

        comm.send_one_message({"type": "LEDGER_SNAPSHOT_END"})

    def request_ledger_from_peer(self, peer_ip: str, peer_port: int):
        client = RSA_Client(peer_ip, int(peer_port), name=f"{self.node_id}_peer_sync")
        try:
            client.sock.connect((peer_ip, int(peer_port)))
            client.contact_with_RSA()
            comm = client.communication
            comm.send_one_message({"type": "GET_LEDGER"})

            start = comm.recv_one_message()
            if not start or str(start.get("type", "")).upper() != "LEDGER_SNAPSHOT_START":
                return False
            total_chunks = int(start.get("chunks", 0))

            parts = [b""] * total_chunks
            received = 0
            while received < total_chunks:
                part = comm.recv_one_message()
                if not part:
                    return False
                msg_type = str(part.get("type", "")).upper()
                if msg_type == "LEDGER_SNAPSHOT_CHUNK":
                    idx = int(part.get("index", -1))
                    if 0 <= idx < total_chunks:
                        parts[idx] = base64.b64decode(str(part.get("data_b64", "")).encode("ascii"))
                        received += 1
                elif msg_type == "LEDGER_SNAPSHOT_END":
                    break

            payload = json.loads(b"".join(parts).decode("utf-8"))
            ledger = payload.get("ledger") if isinstance(payload.get("ledger"), list) else []
            balances = payload.get("balances") if isinstance(payload.get("balances"), dict) else {}

            with self.lock:
                self.chain = ledger
                self.balances = {k: float(v) for k, v in balances.items()}
                self._persist_local_state()

            self.Print(f"[{self.node_id}] ledger synced from {peer_ip}:{peer_port}")
            return True
        except Exception as exc:
            self.Print(f"[{self.node_id}] ledger sync failed from {peer_ip}:{peer_port}: {exc}")
            return False
        finally:
            try:
                client.close()
            except Exception:
                pass

    def request_balance_from_peer(self, peer_ip: str, peer_port: int, userpk: str):
        client = RSA_Client(peer_ip, int(peer_port), name=f"{self.node_id}_balance_sync")
        try:
            client.sock.connect((peer_ip, int(peer_port)))
            client.contact_with_RSA()
            comm = client.communication
            comm.send_one_message({"type": "GET_BALANCE", "userpk": userpk})
            resp = comm.recv_one_message()
            if not resp or str(resp.get("type", "")).upper() != "BALANCE_RESPONSE":
                return False
            balance = float(resp.get("balance", 0.0))
            with self.lock:
                self.balances[userpk] = balance
                self._persist_local_state()
            return True
        except Exception as exc:
            self.Print(f"[{self.node_id}] balance sync failed from {peer_ip}:{peer_port}: {exc}")
            return False
        finally:
            try:
                client.close()
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Aurex updated blockchain node")
    parser.add_argument("--ip", default="0.0.0.0")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--difficulty", type=int, default=2)
    parser.add_argument("--symbol", default="A")
    args = parser.parse_args()

    node = BlockchainNode(args.ip, args.port, difficulty=args.difficulty, symbol=args.symbol)
    node.start()
