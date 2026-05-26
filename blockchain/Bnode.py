__author__ = "Nadav"

import argparse
import base64
import hashlib
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# Adds the root folder to enable imports from SharedResources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SharedResources.classes import RSA_Client, RSA_Server
from SharedResources.config import GATEWAY_UDP_PORT, BROADCAST_DISCOVERY_FREQUENCY, POW_DIFFICULTY, INITIAL_BALANCE
from SharedResources.logging import Logger


class BlockchainNode:
    """Single-file blockchain node runtime with gateway relay + peer ledger sync."""

    CHUNK_SIZE = 8192

    def __init__(self, port: int = 0, difficulty: int = 2):
        self.ip = "0.0.0.0"
        self.port = int(port)
        self.difficulty = int(difficulty)

        self.logger = Logger("Bnode")
        self.Print = lambda *args: self.logger.info(" ".join(str(a) for a in args))

        self.base_dir = Path(__file__).resolve().parent
        self.server_for_peers = RSA_Server(
            self.ip,
            self.port,
            dir_for_keys=None,
            name="NodePeerServer",
            peer_label="Bnode",
        )
        self.server_for_peers.handle_client = self.handle_peer_connection

        # Resolve effective bind values (port may be OS-assigned when 0).
        self.ip, self.port = self.server_for_peers.sock.getsockname()
        self.ip = str(self.ip)
        self.port = int(self.port)
        self.node_id = f"node_{self.ip}_{self.port}"

        # Node local storage per node_<ip>_<port>/
        self.node_dir = self.base_dir / self.node_id
        self.node_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = self.node_dir / "ledger.json"
        self.balances_path = self.node_dir / "balances.json"
        self.node_keys_dir = self.node_dir / "Node_keys"
        self.node_keys_dir.mkdir(parents=True, exist_ok=True)
        self.server_for_peers.dir_for_keys = str(self.node_keys_dir)

        self.lock = threading.RLock()
        self.stop_event = threading.Event()

        self.chain: list[dict[str, Any]] = []
        self.balances: dict[str, float] = {}
        self.pending_txs: list[dict[str, Any]] = []

        self.gateway_client: RSA_Client | None = None
        self.gateway_comm = None

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

    def _discover_gateway_once(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(float(BROADCAST_DISCOVERY_FREQUENCY))
            self.logger.debug(f"[{self.node_id}] Sent to Gateway at 255.255.255.255:{GATEWAY_UDP_PORT} >>> WHRSV")
            sock.sendto(b"WHRSV", ("255.255.255.255", int(GATEWAY_UDP_PORT)))
            raw, addr = sock.recvfrom(1024)
            response = raw.decode("utf-8", errors="ignore")
            self.logger.debug(f"[{self.node_id}] Recv From Gateway at {addr[0]}:{addr[1]} <<< {response}")
            parts = response.split("|")
            if len(parts) != 3 or parts[0] != "SRVAT":
                return None
            return parts[1], int(parts[2])
        except Exception:
            return None
        finally:
            sock.close()

    def connect_to_gateway(self):
        while not self.stop_event.is_set():
            discovered = self._discover_gateway_once()
            if not discovered:
                self.Print(f"[{self.node_id}] gateway not discovered, retry in {BROADCAST_DISCOVERY_FREQUENCY}s")
                time.sleep(float(BROADCAST_DISCOVERY_FREQUENCY))
                continue

            gw_ip, gw_port = discovered
            try:
                client = RSA_Client(gw_ip, gw_port, name=f"{self.node_id}_to_gateway", peer_label="Gateway")
                client.sock.connect((gw_ip, gw_port))
                client.contact_with_RSA()
                self.gateway_client = client
                self.gateway_comm = client.communication
                threading.Thread(target=self._listen_gateway_loop, daemon=True).start()
                self.register_blockchain_node()
                self.Print(f"[{self.node_id}] connected to gateway at {gw_ip}:{gw_port}")
                return
            except Exception as exc:
                self.Print(f"[{self.node_id}] gateway connect failed: {exc}; retry in {BROADCAST_DISCOVERY_FREQUENCY}s")
                time.sleep(float(BROADCAST_DISCOVERY_FREQUENCY))

    def _listen_gateway_loop(self):
        while not self.stop_event.is_set() and self.gateway_comm is not None:
            msg = self.gateway_comm.recv_one_message()
            if not msg:
                break
            self._handle_gateway_message(msg)
        if not self.stop_event.is_set():
            self.gateway_comm = None
            self.gateway_client = None
            self.Print(f"[{self.node_id}] gateway disconnected, reconnecting")
            self.connect_to_gateway()

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

    def _find_asset_owner_pk(self, asset_id: str) -> str:
        """Search ledger for the current owner's public key for a given asset.

        Returns the ASSET_MINT owner PK for a fresh asset, or the most recent
        BUY sender PK (the buyer who is now the owner and will be the next seller).
        """
        owner_pk = ""
        with self.lock:
            for block in self.chain:
                tx = block.get("tx") if isinstance(block.get("tx"), dict) else {}
                tx_type = str(tx.get("tx_type") or tx.get("type") or "")
                if str(tx.get("asset_id", "")) != asset_id:
                    continue
                if tx_type == "ASSET_MINT":
                    owner_pk = str(tx.get("owner_public_key") or tx.get("sender") or "")
                elif tx_type == "BUY":
                    # After each BUY the buyer (sender) becomes the new owner
                    owner_pk = str(tx.get("sender", ""))
        return owner_pk

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
            self.Print(f"[{self.node_id}] mine: tx validation failed for tx_type={transaction.get('tx_type', transaction.get('type', 'TX'))}")
            return None

        tx_label = transaction.get("tx_type") or transaction.get("type") or "TX"
        self.Print(f"[{self.node_id}] mine: starting PoW for {tx_label} difficulty={self.difficulty}...")

        new_block = {
            "index": len(self.chain),
            "prev_hash": self._last_hash(),
            "timestamp": datetime.now().isoformat(),
            "tx": transaction,
            "public_key": str(transaction.get("public_key", "")),
            "signature": str(transaction.get("signature", "")),
            "nonce": 0,
            "difficulty": self.difficulty,
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
        self.Print(f"[{self.node_id}] mine: block found nonce={new_block['nonce']} hash={new_block['hash'][:16]}...")
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
            if sender and amount > 0:
                self.balances[sender] = round(float(self.balances.get(sender, 0.0)) - amount, 8)
            if receiver and amount > 0:
                self.balances[receiver] = round(float(self.balances.get(receiver, 0.0)) + amount, 8)

            self.chain.append(block)
            self.pending_txs = []
            self._persist_local_state()

    # -------- gateway communication --------

    def _send_gateway(self, msg: dict[str, Any]):
        if not self.gateway_comm:
            return
        try:
            self.gateway_comm.send_one_message(msg)
        except Exception as exc:
            self.Print(f"[{self.node_id}] gateway send failed: {exc}")

    def _advertised_ip(self) -> str:
        try:
            if self.gateway_client and self.gateway_client.sock:
                local_ip = str(self.gateway_client.sock.getsockname()[0])
                if local_ip and local_ip != "0.0.0.0":
                    return local_ip
        except Exception:
            pass
        return self.ip

    def register_blockchain_node(self):
        self._send_gateway(
            {
                "type": "REGISTER_BLOCKCHAIN_NODE",
                "data": {"ip": self._advertised_ip(), "port": self.port, "chain_length": len(self.chain)},
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            }
        )

    def notify_gateway(self, block: dict[str, Any]):
        self._send_gateway(
            {
                "type": "BROADCAST_TX_TO_VERIFY",
                "data": {
                    "block": block,
                    "publisher_chain_length": len(self.chain),
                },
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            }
        )

    def notify_buy_success(self, tx_data: dict[str, Any]):
        self._send_gateway(
            {
                "type": "BUY_SUCCESS",
                "data": tx_data,
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            }
        )

    def notify_sell_success(self, tx_data: dict[str, Any]):
        self._send_gateway(
            {
                "type": "SELL_SUCCESS",
                "data": tx_data,
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            }
        )

    def send_balance(self, userpk: str):
        self._send_gateway(
            {
                "type": "SEND_BALANCE",
                "userpk": userpk,
                "data": {"userpk": userpk, "balance": self.get_balance(userpk)},
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            }
        )

    def _handle_gateway_message(self, msg: dict[str, Any]):
        msg_type = str(msg.get("type", "")).strip().upper()

        if msg_type == "TX_REQUEST_BUY":
            self.handle_tx_request_buy(msg)
            return
        if msg_type == "TX_REQUEST_SELL":
            self.handle_tx_request_sell(msg)
            return
        if msg_type == "BROADCAST_TX_TO_VERIFY":
            self.handle_broadcast_tx_to_verify(msg)
            return
        if msg_type in {"UPLOAD_ASSET", "START_MINING"}:
            threading.Thread(target=self._handle_mint_request, args=(msg,), daemon=True).start()
            return
        if msg_type == "UNLIST_ASSET":
            threading.Thread(target=self._handle_unlist_request, args=(msg,), daemon=True).start()
            return
        if msg_type == "CREATE_BALANCE":
            self.handle_create_balance(msg)
            return
        if msg_type == "GET_LEDGER":
            self.handle_get_ledger_sync(msg)
            return
        if msg_type == "GET_BALANCE":
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

        buyer_username = str(payload.get("buyer") or payload.get("sender_username") or "")
        # sender = buyer's public key (they deduct balance); NOT their username
        buyer_pk = str(payload.get("public_key") or payload.get("sender") or "")
        asset_id = str(payload.get("asset_id") or "")

        # For BUY txs find the current asset owner PK from the ledger — they are the seller (receiver of AUR)
        seller_pk = ""
        if tx_type == "BUY" and asset_id:
            seller_pk = self._find_asset_owner_pk(asset_id)

        tx = {
            "type": tx_type,
            "tx_id": payload.get("tx_id") or f"{tx_type}-{int(time.time() * 1000)}",
            "sender": buyer_pk,
            "receiver": seller_pk,
            "buyer_username": buyer_username,
            "amount": float(payload.get("amount") or payload.get("price") or 0.0),
            "asset_id": asset_id,
            "timestamp": payload.get("timestamp") or datetime.now().isoformat(),
            "data": payload.get("data") if isinstance(payload.get("data"), dict) else payload,
            "signature": str(payload.get("signature", "")),
            "public_key": buyer_pk,
        }
        return tx

    def _handle_mint_request(self, msg: dict[str, Any]):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        asset_id = str(data.get("asset_id", ""))
        owner = str(data.get("owner", ""))
        public_key = str(data.get("public_key", ""))
        signature = str(data.get("signature", ""))
        file_hash = str(data.get("file_hash", ""))

        if not asset_id:
            self.Print(f"[{self.node_id}] ASSET_MINT: missing asset_id, skipping")
            return

        tx = {
            "tx_type": "ASSET_MINT",
            "tx_id": f"mint-{asset_id}-{int(time.time() * 1000)}",
            "asset_id": asset_id,
            "owner_public_key": public_key,
            "owner_username": owner,
            "sender": public_key,
            "receiver": "",
            "amount": 0.0,
            "signature": signature,
            "public_key": public_key,
            "timestamp": datetime.now().isoformat(),
            "img_hash": file_hash,
        }

        self.Print(f"[{self.node_id}] ASSET_MINT: starting mining for asset_id={asset_id}")
        block = self.mine(tx)
        if block is not None:
            self.Print(f"[{self.node_id}] ASSET_MINT: mined asset_id={asset_id} nonce={block['nonce']} hash={block['hash'][:16]}...")
            self._send_gateway({
                "type": "ASSET_SIGNED_IN_BLOCKCHAIN",
                "data": {
                    "block": block,
                    "asset_id": asset_id,
                    "owner": owner,
                },
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            })
        else:
            self.Print(f"[{self.node_id}] ASSET_MINT: mining failed for asset_id={asset_id}")

    def _handle_unlist_request(self, msg: dict[str, Any]):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        asset_id = str(data.get("asset_id", ""))
        owner = str(data.get("owner", ""))
        public_key = str(data.get("public_key", ""))
        signature = str(data.get("signature", ""))

        if not asset_id:
            self.Print(f"[{self.node_id}] UNLIST: missing asset_id, skipping")
            return

        tx = {
            "tx_type": "UNLIST_ASSET_FROM_BLOCKCHAIN",
            "tx_id": f"unlist-{asset_id}-{int(time.time() * 1000)}",
            "asset_id": asset_id,
            "owner_username": owner,
            "sender": public_key,
            "receiver": "",
            "amount": 0.0,
            "signature": signature,
            "public_key": public_key,
            "timestamp": datetime.now().isoformat(),
        }

        self.Print(f"[{self.node_id}] UNLIST: starting mining for asset_id={asset_id}")
        block = self.mine(tx)
        if block is not None:
            self.Print(f"[{self.node_id}] UNLIST: mined asset_id={asset_id} nonce={block['nonce']} hash={block['hash'][:16]}...")
            self._send_gateway({
                "type": "ASSET_UNLIST_SIGNED_IN_BLOCKCHAIN",
                "data": {
                    "block": block,
                    "asset_id": asset_id,
                    "owner": owner,
                },
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            })
        else:
            self.Print(f"[{self.node_id}] UNLIST: mining failed for asset_id={asset_id}")

    def handle_tx_request_buy(self, msg: dict[str, Any]):
        tx = self._tx_from_gateway_message(msg, "BUY")
        self.pending_txs.append(tx)
        block = self.mine(tx)
        if block is not None:
            self.notify_buy_success(tx)
            # Send fresh balance to both buyer and seller so UI updates immediately
            buyer_pk = str(tx.get("sender", ""))
            seller_pk = str(tx.get("receiver", ""))
            if buyer_pk:
                self.send_balance(buyer_pk)
            if seller_pk and seller_pk != buyer_pk:
                self.send_balance(seller_pk)
            self.notify_gateway(block)

    def handle_tx_request_sell(self, msg: dict[str, Any]):
        tx = self._tx_from_gateway_message(msg, "SELL")
        self.pending_txs.append(tx)
        block = self.mine(tx)
        if block is not None:
            self.notify_sell_success(tx)
            self.notify_gateway(block)

    def handle_create_balance(self, msg: dict[str, Any]):
        public_key = str(msg.get("public_key") or "")
        if not public_key:
            data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
            public_key = str(data.get("public_key") or "")
        if not public_key:
            return
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        target_balance = msg.get("balance", data.get("balance", INITIAL_BALANCE))
        try:
            target_balance = float(target_balance)
        except Exception:
            target_balance = float(INITIAL_BALANCE)
        with self.lock:
            if public_key not in self.balances:
                self.balances[public_key] = target_balance
                self._persist_local_state()

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
            self.register_blockchain_node()

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
        client = RSA_Client(peer_ip, int(peer_port), name=f"{self.node_id}_peer_sync", peer_label="Bnode")
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
        client = RSA_Client(peer_ip, int(peer_port), name=f"{self.node_id}_balance_sync", peer_label="Bnode")
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
    parser = argparse.ArgumentParser(
        description="Aurex blockchain node. If --port is omitted, the OS will choose a free port."
    )
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--difficulty", type=int, default=POW_DIFFICULTY)
    parser.add_argument(
        "--debug-level", "--DEBUG_LEVEL",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    from SharedResources.logging import Logger as _Logger
    _Logger.set_level(args.debug_level)

    if args.port == 0:
        print("[*] No --port provided. OS will assign a free port.")
    node = BlockchainNode(port=args.port, difficulty=args.difficulty)
    print(f"[*] Node initialized at {node.ip}:{node.port}")
    print(f"[*] Node keys directory: {node.node_keys_dir}")
    node.start()
