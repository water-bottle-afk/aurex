__author__ = "Nadav"

import argparse
import base64
import hashlib
import json
import multiprocessing
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


# ── Module-level mining worker (must be top-level for multiprocessing spawn on Windows) ──

def _mine_worker(block_template: dict, difficulty: int, stop_event, child_conn):
    """Subprocess mining worker — pure stdlib, no project imports needed."""
    import hashlib as _hl
    import json as _json
    target = "0" * difficulty
    block = dict(block_template)
    while not stop_event.is_set():
        raw = _json.dumps(block, sort_keys=True, separators=(",", ":")).encode()
        digest = _hl.sha256(raw).hexdigest()
        if digest.startswith(target):
            block["hash"] = digest
            try:
                child_conn.send(block)
            except Exception:
                pass
            break
        block["nonce"] += 1
    child_conn.close()


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

        self.ip, self.port = self.server_for_peers.sock.getsockname()
        self.ip = str(self.ip)
        self.port = int(self.port)
        self.node_id = f"node_{self.ip}_{self.port}"

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

        # Active mining subprocesses keyed by tx_id
        self.active_mining: dict[str, tuple[multiprocessing.Process, Any, Any]] = {}
        self.active_mining_lock = threading.Lock()

        # Dict-based message dispatch
        self.handlers: dict[str, Any] = {
            "TX_REQUEST_BUY": self.handle_tx_request_buy,
            "TX_REQUEST_SELL": self.handle_tx_request_sell,
            "BROADCAST_TX_TO_VERIFY": self.handle_broadcast_tx_to_verify,
            "UPLOAD_ASSET": self._handle_mint_request,
            "START_MINING": self._handle_mint_request,
            "UNLIST_ASSET": self._handle_unlist_request,
            "CREATE_BALANCE": self.handle_create_balance,
            "GET_LEDGER": self.handle_get_ledger_sync,
            "GET_BALANCE": self._handle_get_balance,
            "HANDLE_GET_BALANCE": self._handle_get_balance,
        }

        self._load_local_state()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

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
            sock.sendto(b"WHRSV", ("255.255.255.255", int(GATEWAY_UDP_PORT)))
            raw, addr = sock.recvfrom(1024)
            response = raw.decode("utf-8", errors="ignore")
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

    # ── Local persistence ─────────────────────────────────────────────────────

    def _load_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
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
            if self.chain and not self.balances:
                # balances.json is stale — will be fixed when this node syncs from a peer
                self.Print(f"[{self.node_id}] WARNING: chain has {len(self.chain)} blocks but balances.json is empty — will sync from peer on connect")
            self._save_json(self.ledger_path, self.chain)
            self._save_json(self.balances_path, self.balances)

    def _persist_local_state(self):
        with self.lock:
            self._save_json(self.ledger_path, self.chain)
            self._save_json(self.balances_path, self.balances)

    # ── Blockchain logic ──────────────────────────────────────────────────────

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

    def _verify_block_hash(self, block: dict[str, Any]) -> bool:
        """Recompute hash from block contents (excluding 'hash' field) and verify PoW."""
        block_copy = {k: v for k, v in block.items() if k != "hash"}
        claimed = str(block.get("hash", ""))
        recomputed = self._block_hash(block_copy)
        if claimed != recomputed:
            self.Print(f"[{self.node_id}] block hash mismatch: claimed={claimed[:16]} recomputed={recomputed[:16]}")
            return False
        difficulty = int(block.get("difficulty", self.difficulty))
        if not recomputed.startswith("0" * difficulty):
            self.Print(f"[{self.node_id}] block PoW invalid: hash={recomputed[:16]} difficulty={difficulty}")
            return False
        return True

    def _find_asset_owner_pk(self, asset_id: str) -> str:
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
                    owner_pk = str(tx.get("sender", ""))
        return owner_pk

    def validate_tx(self, tx: dict[str, Any]) -> bool:
        sender = str(tx.get("sender", ""))
        amount = float(tx.get("amount", 0.0))
        if amount < 0:
            return False
        if sender and self.get_balance(sender) < amount:
            self.Print(f"[{self.node_id}] validate_tx: insufficient balance for {sender[:12]}...")
            return False
        return True

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

    # ── Subprocess mining ─────────────────────────────────────────────────────

    def mine_and_notify(self, tx: dict[str, Any], on_success):
        """Start a non-blocking mining subprocess. on_success(block) is called in a
        watcher thread when this node wins. The subprocess is stopped if
        handle_broadcast_tx_to_verify signals that another node won first."""
        if not self.validate_tx(tx):
            self.Print(f"[{self.node_id}] mine_and_notify: tx validation failed, skipping")
            return

        tx_id = str(tx.get("tx_id") or tx.get("asset_id") or f"tx-{int(time.time()*1000)}")
        tx_label = tx.get("tx_type") or tx.get("type") or "TX"

        with self.lock:
            block_template = {
                "index": len(self.chain),
                "prev_hash": self._last_hash(),
                "timestamp": datetime.now().isoformat(),
                "tx": tx,
                "public_key": str(tx.get("public_key", "")),
                "signature": str(tx.get("signature", "")),
                "nonce": 0,
                "difficulty": self.difficulty,
            }

        stop_event = multiprocessing.Event()
        parent_conn, child_conn = multiprocessing.Pipe(duplex=False)
        process = multiprocessing.Process(
            target=_mine_worker,
            args=(block_template, self.difficulty, stop_event, child_conn),
            daemon=True,
        )

        with self.active_mining_lock:
            self.active_mining[tx_id] = (process, stop_event, parent_conn)

        process.start()
        child_conn.close()  # parent never writes to child end

        self.Print(f"[{self.node_id}] mine_and_notify: subprocess pid={process.pid} tx_id={tx_id[:20]} ({tx_label})")

        def _watcher():
            block_received = None
            try:
                # Poll until data arrives OR the process exits.
                # The race: process may exit between is_alive() and poll(), so after
                # the loop we do a final non-blocking drain to catch that case.
                while True:
                    if parent_conn.poll(0.1):
                        try:
                            block_received = parent_conn.recv()
                        except (EOFError, OSError):
                            pass
                        break
                    if not process.is_alive():
                        # Process exited without us catching it in poll; drain now.
                        if parent_conn.poll(0):
                            try:
                                block_received = parent_conn.recv()
                            except (EOFError, OSError):
                                pass
                        break

                if block_received is not None and not stop_event.is_set():
                    block = block_received
                    with self.lock:
                        valid = (
                            int(block.get("index", -1)) == len(self.chain)
                            and str(block.get("prev_hash", "")) == self._last_hash()
                            and self._verify_block_hash(block)
                        )
                    if valid:
                        self.add_block(block)
                        self.Print(f"[{self.node_id}] block mined nonce={block['nonce']} hash={block.get('hash','?')[:16]}...")
                        on_success(block)
                    else:
                        self.Print(f"[{self.node_id}] mined block invalid (stale chain or bad hash), discarding")
                elif block_received is not None:
                    self.Print(f"[{self.node_id}] mined block arrived after stop signal — discarding")
            except Exception as exc:
                self.Print(f"[{self.node_id}] mining watcher error: {exc}")
            finally:
                with self.active_mining_lock:
                    self.active_mining.pop(tx_id, None)
                try:
                    parent_conn.close()
                except Exception:
                    pass
                if process.is_alive():
                    process.terminate()
                try:
                    process.join(timeout=2)  # reap to prevent zombie
                except Exception:
                    pass

        threading.Thread(target=_watcher, daemon=True).start()

    def _stop_mining(self, tx_id: str):
        """Set stop signal, terminate the subprocess, and join it to prevent zombies."""
        with self.active_mining_lock:
            entry = self.active_mining.pop(tx_id, None)
        if not entry:
            return
        process, stop_event, parent_conn = entry
        stop_event.set()
        try:
            parent_conn.close()
        except Exception:
            pass
        if process.is_alive():
            process.terminate()
        try:
            process.join(timeout=2)  # reap to prevent zombie
        except Exception:
            pass
        self.Print(f"[{self.node_id}] stopped mining tx_id={tx_id[:20]} (peer won)")

    # ── Gateway communication ─────────────────────────────────────────────────

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
        # node_server_ip/port = the P2P peer-server address (for other nodes to sync from).
        # This is distinct from the ephemeral port used for the gateway TCP connection.
        self._send_gateway({
            "type": "REGISTER_BLOCKCHAIN_NODE",
            "data": {
                "node_server_ip": self._advertised_ip(),
                "node_server_port": self.port,
                "chain_length": len(self.chain),
            },
            "sender_ip": self._advertised_ip(),
            "sender_port": self.port,
        })

    def notify_gateway(self, block: dict[str, Any]):
        self._send_gateway({
            "type": "BROADCAST_TX_TO_VERIFY",
            "data": {
                "block": block,
                "publisher_chain_length": len(self.chain),
            },
            "sender_ip": self._advertised_ip(),
            "sender_port": self.port,
        })

    def notify_buy_success(self, tx_data: dict[str, Any]):
        self._send_gateway({
            "type": "BUY_SUCCESS",
            "data": tx_data,
            "sender_ip": self._advertised_ip(),
            "sender_port": self.port,
        })

    def notify_sell_success(self, tx_data: dict[str, Any]):
        self._send_gateway({
            "type": "SELL_SUCCESS",
            "data": tx_data,
            "sender_ip": self._advertised_ip(),
            "sender_port": self.port,
        })

    def send_balance(self, userpk: str):
        self._send_gateway({
            "type": "SEND_BALANCE",
            "userpk": userpk,
            "data": {"userpk": userpk, "balance": self.get_balance(userpk)},
            "sender_ip": self._advertised_ip(),
            "sender_port": self.port,
        })

    # ── Gateway message dispatch ──────────────────────────────────────────────

    def _handle_gateway_message(self, msg: dict[str, Any]):
        msg_type = str(msg.get("type", "")).strip().upper()
        handler = self.handlers.get(msg_type)
        if handler:
            handler(msg)
        else:
            self.Print(f"[{self.node_id}] unhandled gateway message type: {msg_type}")

    # ── Per-message handlers ──────────────────────────────────────────────────

    def _tx_from_gateway_message(self, msg: dict[str, Any], tx_type: str) -> dict[str, Any]:
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        payload = data.get("data") if isinstance(data.get("data"), dict) else data

        buyer_pk = str(payload.get("public_key") or payload.get("sender") or "")
        asset_id = str(payload.get("asset_id") or "")
        buyer_username = str(payload.get("buyer") or payload.get("sender_username") or "")

        seller_pk = ""
        if tx_type == "BUY" and asset_id:
            seller_pk = self._find_asset_owner_pk(asset_id)

        return {
            "type": tx_type,
            "tx_type": tx_type,
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

    def handle_tx_request_buy(self, msg: dict[str, Any]):
        tx = self._tx_from_gateway_message(msg, "BUY")
        self.pending_txs.append(tx)

        def _on_success(block):
            self.notify_buy_success(tx)
            buyer_pk = str(tx.get("sender", ""))
            seller_pk = str(tx.get("receiver", ""))
            if buyer_pk:
                self.send_balance(buyer_pk)
            if seller_pk and seller_pk != buyer_pk:
                self.send_balance(seller_pk)
            self.notify_gateway(block)

        self.mine_and_notify(tx, _on_success)

    def handle_tx_request_sell(self, msg: dict[str, Any]):
        tx = self._tx_from_gateway_message(msg, "SELL")
        self.pending_txs.append(tx)

        def _on_success(block):
            self.notify_sell_success(tx)
            self.notify_gateway(block)

        self.mine_and_notify(tx, _on_success)

    def _handle_mint_request(self, msg: dict[str, Any]):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        asset_id = str(data.get("asset_id", ""))
        owner = str(data.get("owner", ""))
        public_key = str(data.get("public_key", ""))
        signature = str(data.get("signature", ""))
        file_hash = str(data.get("file_hash", ""))
        tx_id = str(data.get("tx_id") or f"mint-{asset_id}-{int(time.time()*1000)}")

        if not asset_id:
            self.Print(f"[{self.node_id}] ASSET_MINT: missing asset_id, skipping")
            return

        tx = {
            "tx_type": "ASSET_MINT",
            "tx_id": tx_id,
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

        def _on_success(block):
            self.Print(f"[{self.node_id}] ASSET_MINT mined asset_id={asset_id} hash={block.get('hash','?')[:16]}...")
            self._send_gateway({
                "type": "ASSET_SIGNED_IN_BLOCKCHAIN",
                "data": {"block": block, "asset_id": asset_id, "owner": owner},
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            })

        self.mine_and_notify(tx, _on_success)

    def _handle_unlist_request(self, msg: dict[str, Any]):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        asset_id = str(data.get("asset_id", ""))
        owner = str(data.get("owner", ""))
        public_key = str(data.get("public_key", ""))
        signature = str(data.get("signature", ""))
        tx_id = str(data.get("tx_id") or f"unlist-{asset_id}-{int(time.time()*1000)}")

        if not asset_id:
            self.Print(f"[{self.node_id}] UNLIST: missing asset_id, skipping")
            return

        tx = {
            "tx_type": "UNLIST_ASSET_FROM_BLOCKCHAIN",
            "tx_id": tx_id,
            "asset_id": asset_id,
            "owner_username": owner,
            "sender": public_key,
            "receiver": "",
            "amount": 0.0,
            "signature": signature,
            "public_key": public_key,
            "timestamp": datetime.now().isoformat(),
        }

        def _on_success(block):
            self.Print(f"[{self.node_id}] UNLIST mined asset_id={asset_id} hash={block.get('hash','?')[:16]}...")
            self._send_gateway({
                "type": "ASSET_UNLIST_SIGNED_IN_BLOCKCHAIN",
                "data": {"block": block, "asset_id": asset_id, "owner": owner},
                "sender_ip": self._advertised_ip(),
                "sender_port": self.port,
            })

        self.mine_and_notify(tx, _on_success)

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
        block = data.get("block") if isinstance(data.get("block"), dict) else {}

        if not block:
            return

        # Stop local mining if we are working on the same tx
        tx = block.get("tx") if isinstance(block.get("tx"), dict) else {}
        tx_id = str(tx.get("tx_id") or tx.get("asset_id") or "")
        if tx_id:
            self._stop_mining(tx_id)

        if publisher_chain_length > len(self.chain) + 1:
            self.ensure_local_state_or_fetch(
                sender_ip, sender_port, publisher_chain_length, str(data.get("userpk") or "")
            )
            return

        with self.lock:
            if (int(block.get("index", -1)) == len(self.chain)
                    and str(block.get("prev_hash", "")) == self._last_hash()
                    and self._verify_block_hash(block)):
                self.add_block(block)
                self.register_blockchain_node()

    def _handle_get_balance(self, msg: dict[str, Any]):
        if msg.get("publisher_ip") and msg.get("publisher_port"):
            self.handle_get_balance_sync(msg)
            return
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        userpk = msg.get("userpk") or data.get("userpk")
        if userpk:
            self.send_balance(str(userpk))

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

    # ── Peer ledger sharing ───────────────────────────────────────────────────

    def ensure_local_state_or_fetch(self, publisher_ip: str, publisher_port: int,
                                    publisher_chain_length: int = 0, userpk: str = ""):
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
                comm.send_one_message({
                    "type": "BALANCE_RESPONSE",
                    "userpk": userpk,
                    "balance": self.get_balance(userpk),
                })

    def _send_ledger_snapshot(self, comm):
        snapshot = {
            "ledger": self.chain,
            "balances": self.balances,
            "publisher": {"ip": self.ip, "port": self.port, "node_id": self.node_id},
        }
        raw = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
        chunks = [raw[i: i + self.CHUNK_SIZE] for i in range(0, len(raw), self.CHUNK_SIZE)]

        comm.send_one_message({
            "type": "LEDGER_SNAPSHOT_START",
            "chunks": len(chunks),
            "total_bytes": len(raw),
        })
        for idx, chunk in enumerate(chunks):
            comm.send_one_message({
                "type": "LEDGER_SNAPSHOT_CHUNK",
                "index": idx,
                "data_b64": base64.b64encode(chunk).decode("ascii"),
            })
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

            self.Print(f"[{self.node_id}] ledger synced from {peer_ip}:{peer_port} (chain={len(ledger)} blocks, balances={len(self.balances)} entries)")
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
    multiprocessing.freeze_support()  # Required for Windows frozen executables

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
