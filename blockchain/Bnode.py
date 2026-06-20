__author__ = "Nadav"

import argparse
import base64
import hashlib
import json
import multiprocessing as mp
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
from SharedResources.config import GATEWAY_UDP_PORT, BROADCAST_DISCOVERY_FREQUENCY, POW_DIFFICULTY, INITIAL_BALANCE, BLOCKCHAIN_NODE_IP
from SharedResources.logging import Logger
from SharedResources.exceptions import (
    AurexError,
    ValidationError,
    DuplicateError,
    BlockchainError,
)


def _mine_block(block_template: dict, difficulty: int,
                stop_event: "mp.Event", result_queue: "mp.Queue"):
    """Standalone PoW worker run inside a separate Process.

    Must live at module level so Python's 'spawn' start method (Windows) can
    pickle it.  Puts ("found", block) or ("aborted", None) into result_queue.
    """
    target = "0" * difficulty
    block = dict(block_template)
    block["nonce"] = 0
    while not stop_event.is_set():
        content = json.dumps(block, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(content).hexdigest()
        if digest.startswith(target):
            block["hash"] = digest
            result_queue.put(("found", block))
            return
        block["nonce"] += 1
    result_queue.put(("aborted", None))


class BlockchainNode:
    """
Bnode.py — a single Aurex blockchain node.

Each node:
  1. Discovers the gateway via UDP broadcast
  2. Registers itself with the gateway and receives mining tasks
  3. Mines PoW blocks and broadcasts them back through the gateway
  4. Syncs its ledger and balance table with peers when it falls behind

Multiple nodes can run simultaneously; the gateway validates mined blocks and
broadcasts the winner to all other nodes so they stop mining and move on.
"""

    CHUNK_SIZE = 8192

    def __init__(self, ip: str, port: int, difficulty: int):
        self.ip = ip
        self.port = int(port)
        self.difficulty = int(difficulty)

        self.logger = Logger("Bnode")

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
        self._node_stop_event = threading.Event()   # shuts down the whole node
        self._mining_stop_event = mp.Event()        # aborts the current mining task
        self._mining_stop_peer: str = ""            # address of the peer that triggered the last stop
        self._current_miner: "mp.Process | None" = None
        self._pending_mint_ids: set[str] = set()    # asset_ids currently being mined (dedup guard)

        self.chain: list[dict[str, Any]] = []
        self.balances: dict[str, float] = {}
        self.pending_txs: list[dict[str, Any]] = []

        self.gateway_client: RSA_Client | None = None
        self.gateway_comm = None

        self.load_local_state()

    # -------- lifecycle --------

    def start(self):
        """
        Start the node: connect to the gateway, start the peer-server thread,
        then block until ``stop()`` is called.
        """
        self.connect_to_gateway()
        threading.Thread(target=self.server_for_peers.start, daemon=True).start()
        self.logger.info(f"[{self.node_id}] listening for peers at {self.ip}:{self.port}")
        while not self._node_stop_event.is_set():
            time.sleep(0.2)

    def stop(self):
        """Signal the node's main loop and all blocking operations to exit."""
        self._node_stop_event.set()
        self._mining_stop_event.set()
        if self._current_miner and self._current_miner.is_alive():
            self._current_miner.terminate()

    def discover_gateway_once(self):
        """
        Send a single UDP broadcast to discover the gateway and return its address.

        Broadcasts ``WHRSV`` on the local network and waits up to
        ``BROADCAST_DISCOVERY_FREQUENCY`` seconds for a ``SRVAT|ip|port`` reply.

        Returns:
            (gateway_ip, gateway_port) tuple, or None if no response received.
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(float(BROADCAST_DISCOVERY_FREQUENCY))
            sock.sendto(b"WHRSV", ("255.255.255.255", int(GATEWAY_UDP_PORT)))
            
            logger = Logger("Bnode-Discovery")
            logger.debug(f"[{self.node_id}] sent gateway discovery WHRSV to {"255.255.255.255", int(GATEWAY_UDP_PORT)}")
            raw, _ = sock.recvfrom(1024)
            parts = raw.decode("utf-8", errors="ignore").split("|")
            if len(parts) != 3 or parts[0] != "SRVAT":
                return None
            return parts[1], int(parts[2])
        except Exception:
            return None
        finally:
            sock.close()

    def connect_to_gateway(self):
        """
        Discover and establish an encrypted RSA connection to the gateway.

        Retries with ``BROADCAST_DISCOVERY_FREQUENCY`` second delays until a
        gateway responds.  On success, starts the ``_listen_gateway_loop``
        thread and calls ``register_blockchain_node`` to announce this node.
        Blocks until a connection is established (or ``stop()`` is called).
        """
        while not self._node_stop_event.is_set():
            discovered = self.discover_gateway_once()
            if not discovered:
                self.logger.warning(f"[{self.node_id}] gateway not discovered, retry in {BROADCAST_DISCOVERY_FREQUENCY}s")
                time.sleep(float(BROADCAST_DISCOVERY_FREQUENCY))
                continue

            gw_ip, gw_port = discovered
            try:
                client = RSA_Client(gw_ip, gw_port, name=f"{self.node_id}_to_gateway", peer_label="Gateway")
                client.sock.connect((gw_ip, gw_port))
                client.contact_with_RSA()
                self.gateway_client = client
                self.gateway_comm = client.communication
                threading.Thread(target=self.listen_gateway_loop, daemon=True).start()
                self.register_blockchain_node()
                self.logger.info(f"[{self.node_id}] connected to gateway at {gw_ip}:{gw_port}")
                return
            except Exception as exc:
                self.logger.warning(f"[{self.node_id}] gateway connect failed: {exc}; retry in {BROADCAST_DISCOVERY_FREQUENCY}s")
                time.sleep(float(BROADCAST_DISCOVERY_FREQUENCY))

    def listen_gateway_loop(self):
        while not self._node_stop_event.is_set() and self.gateway_comm is not None:
            msg = self.gateway_comm.recv_one_message()
            if not msg:
                break
            self.handle_gateway_message(msg)
        if not self._node_stop_event.is_set():
            self.gateway_comm = None
            self.gateway_client = None
            self.logger.warning(f"[{self.node_id}] gateway disconnected, reconnecting")
            self.connect_to_gateway()

    def load_json(self, path: Path, default):
        if not path.exists():
            return default
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return default

    def save_json(self, path: Path, data):
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _deduplicate_chain(self, raw: list) -> list:
        """Return a clean chain with at most one block per index.

        Old ledger files may contain competing blocks at the same index (a side-effect
        of the racing-miner bug).  Keep the first occurrence of each index so the
        canonical chain is a strictly ascending sequence 0, 1, 2, …
        Balances are then rebuilt from this clean chain so they reflect reality.
        """
        seen: set[int] = set()
        clean: list[dict] = []
        for block in raw:
            idx = int(block.get("index", -1))
            if idx < 0 or idx in seen:
                continue
            seen.add(idx)
            clean.append(block)
        # Sort so 0,1,2,... even if file was out of order
        clean.sort(key=lambda b: int(b.get("index", 0)))
        return clean

    def _rebuild_balances(self, chain: list) -> dict:
        """Recompute the balance table from scratch by replaying BUY blocks in the chain."""
        balances: dict[str, float] = {}
        for block in chain:
            tx = block.get("tx", {}) if isinstance(block.get("tx"), dict) else {}
            tx_type = str(tx.get("type") or tx.get("tx_type") or "").upper()
            if tx_type == "BUY":
                buyer_pk = str(tx.get("user_public_key") or tx.get("sender") or "")
                seller_pk = str(tx.get("seller_public_key") or "")
                price = float(tx.get("price") or tx.get("amount") or 0.0)
                if buyer_pk and price > 0:
                    balances[buyer_pk] = round(balances.get(buyer_pk, 0.0) - price, 8)
                if seller_pk and price > 0:
                    balances[seller_pk] = round(balances.get(seller_pk, 0.0) + price, 8)
        return balances

    def load_local_state(self):
        with self.lock:
            raw_ledger = self.load_json(self.ledger_path, [])
            raw_balances = self.load_json(self.balances_path, {})
            raw_chain = raw_ledger if isinstance(raw_ledger, list) else []
            clean_chain = self._deduplicate_chain(raw_chain)

            if len(clean_chain) < len(raw_chain):
                # Ledger had duplicate-index blocks — rebuild balances from the clean chain.
                # All users start at INITIAL_BALANCE (set by CREATE_BALANCE on signup, always
                # uses the constant).  Apply BUY deltas from the canonical chain only.
                self.logger.warning(
                    f"[{self.node_id}] load: ledger had {len(raw_chain)} blocks with duplicates; "
                    f"deduped to {len(clean_chain)}; rebuilding balances"
                )
                saved = {k: float(v) for k, v in raw_balances.items()} if isinstance(raw_balances, dict) else {}
                # Seed every known pk at the initial balance
                merged: dict[str, float] = {pk: float(INITIAL_BALANCE) for pk in saved}
                # Re-apply only the canonical BUY deltas
                for pk, delta in self._rebuild_balances(clean_chain).items():
                    merged[pk] = round(merged.get(pk, float(INITIAL_BALANCE)) + delta, 8)
                self.chain = clean_chain
                self.balances = merged
            else:
                self.chain = clean_chain
                self.balances = {k: float(v) for k, v in raw_balances.items()} if isinstance(raw_balances, dict) else {}

            self.save_json(self.ledger_path, self.chain)
            self.save_json(self.balances_path, self.balances)

    def persist_local_state(self):
        """Write the current in-memory chain and balances to disk atomically."""
        with self.lock:
            self.save_json(self.ledger_path, self.chain)
            self.save_json(self.balances_path, self.balances)

    # -------- blockchain logic --------

    def get_balance(self, userpk: str) -> float:
        """
        Return the current balance for a public key.

        Args:
            userpk: Hex-encoded public key to look up.

        Returns:
            Float balance (0.0 if the key has never been seen).
        """
        with self.lock:
            return float(self.balances.get(userpk, 0.0))

    def last_hash(self) -> str:
        """Return the hash of the last block, or 64 zeros for an empty chain."""
        if not self.chain:
            return "0" * 64
        return str(self.chain[-1].get("hash", "0" * 64))

    def block_hash(self, block: dict[str, Any]) -> str:
        """
        Compute the SHA-256 hash of a block dict.

        Keys are sorted and whitespace is eliminated so the same logical block
        always produces the same hash regardless of insertion order.

        Args:
            block: Block dict (must NOT already contain a 'hash' key when
                   computing the target hash for PoW).

        Returns:
            64-character lowercase hex digest.
        """
        content = json.dumps(block, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(content).hexdigest()

    def validate_tx(self, tx: dict[str, Any]):
        sender = str(tx.get("user_public_key") or tx.get("sender") or "")
        amount = float(tx.get("price") or tx.get("amount") or 0.0)
        if amount < 0:
            return False
        if sender and sender in self.balances and self.get_balance(sender) < amount:
            return False
        return True

    def _is_tx_in_chain(self, tx_id: str) -> bool:
        """Return True if a transaction with this tx_id already exists in the local chain."""
        if not tx_id:
            return False
        with self.lock:
            return any(
                isinstance(b.get("tx"), dict) and str(b["tx"].get("tx_id", "")) == tx_id
                for b in self.chain
            )

    def mine(self, transaction: dict[str, Any]):
        """Perform PoW mining in a separate Process (non-blocking for the gateway listener).

        Spawns a multiprocessing.Process running _mine_block so the GIL never
        blocks the gateway listener thread.  The listener can abort mining only
        when BROADCAST_TX_TO_VERIFY arrives and passes validation (chain advanced).
        mine() returns None on abort so the caller can check whether the tx was
        already committed and either discard or retry.

        Returns the mined block dict on success, or None if aborted.
        """
        if not self.validate_tx(transaction):
            self.logger.warning(
                f"[{self.node_id}] mine: tx validation failed for "
                f"tx_type={transaction.get('tx_type', transaction.get('type', 'TX'))}"
            )
            return None

        tx_label = transaction.get("tx_type") or transaction.get("type") or "TX"
        self.logger.info(f"[{self.node_id}] mine: starting PoW for {tx_label} difficulty={self.difficulty}...")

        block_template = {
            "index":      len(self.chain),
            "prev_hash":  self.last_hash(),
            "timestamp":  datetime.now().isoformat(),
            "tx":         transaction,
            "nonce":      0,
            "difficulty": self.difficulty,
        }

        result_queue: mp.Queue = mp.Queue()
        self._mining_stop_event.clear()
        miner = mp.Process(
            target=_mine_block,
            args=(block_template, self.difficulty, self._mining_stop_event, result_queue),
            daemon=True,
        )
        self._current_miner = miner
        miner.start()

        # Block this thread until the miner finishes or the node shuts down
        status, block = None, None
        while not self._node_stop_event.is_set():
            try:
                status, block = result_queue.get(timeout=0.1)
                break
            except Exception:
                continue

        if self._node_stop_event.is_set():
            self._mining_stop_event.set()
            if miner.is_alive():
                miner.terminate()
                miner.join(timeout=2)
            self._current_miner = None
            return None

        miner.join(timeout=5)
        self._current_miner = None

        if status == "aborted":
            peer = self._mining_stop_peer or "unknown"
            self.logger.warning(f"[{self.node_id}] mine: abandoned — peer {peer} already mined it")
            return None

        # If the stop signal arrived just as our miner found the nonce, another winner
        # was already accepted. Discard our block so we don't write a duplicate.
        if self._mining_stop_event.is_set():
            peer = self._mining_stop_peer or "unknown"
            self.logger.warning(
                f"[{self.node_id}] mine: found block but peer {peer} already won — discarding"
            )
            return None

        self.logger.info(f"[{self.node_id}] mine: block found nonce={block['nonce']} hash={block['hash'][:16]}...")
        self.add_block(block)
        return block

    def add_block(self, block: dict[str, Any]):
        """Append a validated block to the chain and update the balance table."""
        tx = block.get("tx", {}) if isinstance(block.get("tx"), dict) else {}
        if not tx and isinstance(block.get("transaction"), dict):
            tx = block.get("transaction")

        tx_type = str(tx.get("type") or tx.get("tx_type") or "").upper()

        with self.lock:
            # Reject blocks that don't sit exactly at the end of our chain.
            # A block already processed by mine() and then received again via broadcast,
            # or a competing block whose peer won the race, must not be appended a second
            # time — doing so would double-apply the balance deduction for BUY blocks.
            expected_index = len(self.chain)
            block_index = int(block.get("index", -1))
            if block_index != expected_index:
                self.logger.warning(
                    f"[{self.node_id}] add_block: rejected block index={block_index} "
                    f"(expected {expected_index}) — stale or duplicate"
                )
                return

            if tx_type == "BUY":
                buyer_pk = str(tx.get("user_public_key") or tx.get("sender") or "")
                seller_pk = str(tx.get("seller_public_key") or "")
                price = float(tx.get("price") or tx.get("amount") or 0.0)
                if buyer_pk and price > 0:
                    self.balances[buyer_pk] = round(float(self.balances.get(buyer_pk, 0.0)) - price, 8)
                if seller_pk and price > 0:
                    self.balances[seller_pk] = round(float(self.balances.get(seller_pk, 0.0)) + price, 8)

            self.chain.append(block)
            self.pending_txs = []
            self.persist_local_state()

    # -------- gateway communication --------

    def send_gateway(self, msg: dict[str, Any]):
        if not self.gateway_comm:
            return
        try:
            self.gateway_comm.send_one_message(msg)
        except Exception as exc:
            self.logger.warning(f"[{self.node_id}] gateway send failed: {exc}")

    def advertised_ip(self) -> str:
        try:
            if self.gateway_client and self.gateway_client.sock:
                local_ip = str(self.gateway_client.sock.getsockname()[0])
                if local_ip and local_ip != "0.0.0.0":
                    return local_ip
        except Exception:
            pass
        return self.ip

    def register_blockchain_node(self):
        self.send_gateway(
            {
                "type": "REGISTER_BLOCKCHAIN_NODE",
                "data": {"ip": self.advertised_ip(), "port": self.port, "chain_length": len(self.chain)},
                "sender_ip": self.advertised_ip(),
                "sender_port": self.port,
            }
        )

    def notify_gateway(self, block: dict[str, Any]):
        self.send_gateway(
            {
                "type": "BROADCAST_TX_TO_VERIFY",
                "data": {
                    "block": block,
                    "publisher_chain_length": len(self.chain),
                },
                "sender_ip": self.advertised_ip(),
                "sender_port": self.port,
            }
        )

    def notify_buy_success(self, tx_data: dict[str, Any]):
        self.send_gateway(
            {
                "type": "BUY_SUCCESS",
                "data": tx_data,
                "sender_ip": self.advertised_ip(),
                "sender_port": self.port,
            }
        )

    def notify_sell_success(self, tx_data: dict[str, Any]):
        self.send_gateway(
            {
                "type": "SELL_SUCCESS",
                "data": tx_data,
                "sender_ip": self.advertised_ip(),
                "sender_port": self.port,
            }
        )

    def send_balance(self, userpk: str):
        self.send_gateway(
            {
                "type": "SEND_BALANCE",
                "userpk": userpk,
                "data": {"userpk": userpk, "balance": self.get_balance(userpk)},
                "sender_ip": self.advertised_ip(),
                "sender_port": self.port,
            }
        )

    def handle_gateway_message(self, msg: dict[str, Any]):
        """Route an incoming gateway message to the right handler."""
        msg_type = str(msg.get("type", "")).strip().upper()

        # Mining is blocking, so it always runs in its own thread
        threaded_handlers = {
            "UPLOAD_ASSET":   self.handle_mint_request,
            "START_MINING":   self.handle_mint_request,
            "UNLIST_ASSET":   self.handle_unlist_request,
            "LIST_ASSET":     self.handle_list_request,
            "TX_REQUEST_BUY": self.handle_tx_request_buy,  # mine() blocks — must not run in listen loop
        }

        # Everything else is fast enough to handle inline
        inline_handlers = {
            "TX_REQUEST_SELL":       self.handle_tx_request_sell,
            "BROADCAST_TX_TO_VERIFY": self.handle_broadcast_tx_to_verify,
            "CREATE_BALANCE":        self.handle_create_balance,
            "GET_LEDGER":            self.handle_get_ledger_sync,
            "GET_MINTED_IDS":        self.handle_get_minted_ids,
        }

        if msg_type in threaded_handlers:
            threading.Thread(target=threaded_handlers[msg_type], args=(msg,), daemon=True).start()
            return

        if msg_type in inline_handlers:
            inline_handlers[msg_type](msg)
            return

        # GET_BALANCE has two paths: peer-sync request (has publisher_ip) vs direct query
        if msg_type == "GET_BALANCE":
            if msg.get("publisher_ip") and msg.get("publisher_port"):
                self.handle_get_balance_sync(msg)
            else:
                data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
                userpk = msg.get("userpk") or data.get("userpk")
                if userpk:
                    self.send_balance(str(userpk))
            return

    def tx_from_gateway_message(self, msg: dict[str, Any], tx_type: str):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        # Client payload may be one level deeper inside a "data" key
        payload = data.get("data") if isinstance(data.get("data"), dict) else data
        signed = payload.get("signed_payload") if isinstance(payload.get("signed_payload"), dict) else {}

        return {
            "type": tx_type,
            "tx_id": str(payload.get("tx_id") or f"{tx_type}-{int(time.time() * 1000)}"),
            "asset_id": str(payload.get("asset_id") or signed.get("asset_id") or ""),
            "buyer": str(payload.get("buyer") or signed.get("buyer") or ""),
            "price": float(payload.get("price") or signed.get("price") or payload.get("amount") or 0.0),
            "user_public_key": str(payload.get("public_key") or ""),
            "seller_public_key": str(payload.get("seller_public_key") or ""),
            "user_signature": str(payload.get("signature") or ""),
            "timestamp": payload.get("timestamp") or signed.get("timestamp") or datetime.now().isoformat(),
        }

    # ── Fail-fast guards ──────────────────────────────────────────────────────

    def _require_asset_id(self, asset_id: str):
        if not asset_id:
            raise ValidationError("Missing asset_id in request")

    def _require_owner(self, owner: str):
        if not owner:
            raise ValidationError("Missing owner in request")

    def _guard_duplicate_pending(self, asset_id: str):
        if asset_id in self._pending_mint_ids:
            raise DuplicateError(f"asset_id={asset_id} already pending mint")

    def _guard_already_minted(self, asset_id: str):
        if self._guard_already_minted_bool(asset_id):
            raise DuplicateError(f"asset_id={asset_id} already minted in chain")

    def _guard_already_minted_bool(self, asset_id: str) -> bool:
        with self.lock:
            return any(
                isinstance(b.get("tx"), dict)
                and str(b["tx"].get("type") or b["tx"].get("tx_type") or "").upper() == "ASSET_MINT"
                and str(b["tx"].get("asset_id", "")) == asset_id
                for b in self.chain
            )

    def _mine_or_raise(self, tx: dict) -> dict:
        block = self.mine(tx)
        if block is None:
            raise BlockchainError("Mining aborted or validation failed")
        return block

    def _build_mint_tx(self, asset_id: str, owner: str, public_key: str,
                       signature: str, file_hash: str = "") -> dict:
        _ = owner
        return {
            "type": "ASSET_MINT",
            "tx_id": f"mint-{asset_id}-{int(time.time() * 1000)}",
            "asset_id": asset_id,
            "user_public_key": public_key,
            "user_signature": signature,
            "img_hash": file_hash,
            "timestamp": datetime.now().isoformat(),
        }

    def handle_mint_request(self, msg: dict[str, Any]):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        asset_id = str(data.get("asset_id", ""))
        owner = str(data.get("owner", ""))
        public_key = str(data.get("public_key", ""))
        signature = str(data.get("signature", ""))
        file_hash = str(data.get("file_hash", ""))

        # Reject if this asset was already minted in our local chain, or if another
        # thread is currently mining it (prevents duplicate blocks when two
        # UPLOAD_ASSET messages arrive before the first one finishes mining).
        try:
            self._require_asset_id(asset_id)
            with self.lock:
                self._guard_already_minted(asset_id)
                self._guard_duplicate_pending(asset_id)
                self._pending_mint_ids.add(asset_id)
        except DuplicateError as e:
            self.logger.warning(f"[{self.node_id}] ASSET_MINT: {e}, skipping")
            return
        except AurexError as e:
            self.logger.warning(f"[{self.node_id}] MINT rejected: {e}")
            return

        try:
            tx = self._build_mint_tx(asset_id, owner, public_key, signature, file_hash)
            self.logger.info(f"[{self.node_id}] ASSET_MINT: starting mining for asset_id={asset_id}")
            while True:
                block = self.mine(tx)
                if block is not None:
                    break
                if self._node_stop_event.is_set():
                    return
                if self._is_tx_in_chain(tx["tx_id"]) or self._guard_already_minted_bool(asset_id):
                    self.logger.info(f"[{self.node_id}] ASSET_MINT: {asset_id} already mined by peer — discarding")
                    return
                self.logger.warning(f"[{self.node_id}] ASSET_MINT: aborted, peer mined different tx — retrying with updated chain")
            self.logger.info(f"[{self.node_id}] ASSET_MINT: mined asset_id={asset_id} nonce={block['nonce']} hash={block['hash'][:16]}...")
            self.send_gateway({
                "type": "ASSET_SIGNED_IN_BLOCKCHAIN",
                "data": {"block": block, "asset_id": asset_id, "owner": owner},
                "sender_ip": self.advertised_ip(),
                "sender_port": self.port,
            })
        except AurexError as e:
            self.logger.error(f"[{self.node_id}] MINT failed: {e}")
        finally:
            with self.lock:
                self._pending_mint_ids.discard(asset_id)

    def handle_unlist_request(self, msg: dict[str, Any]):
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        asset_id = str(data.get("asset_id", ""))
        owner = str(data.get("owner", ""))
        public_key = str(data.get("public_key", ""))
        signature = str(data.get("signature", ""))

        if not asset_id:
            self.logger.warning(f"[{self.node_id}] UNLIST: missing asset_id, skipping")
            return

        tx = {
            "type": "UNLIST",
            "tx_id": str(data.get("tx_id") or f"unlist-{asset_id}-{int(time.time() * 1000)}"),
            "asset_id": asset_id,
            "user_public_key": public_key,
            "user_signature": signature,
            "timestamp": datetime.now().isoformat(),
        }

        self.logger.info(f"[{self.node_id}] UNLIST: starting mining for asset_id={asset_id}")
        while True:
            block = self.mine(tx)
            if block is not None:
                break
            if self._node_stop_event.is_set():
                return
            if self._is_tx_in_chain(tx["tx_id"]):
                self.logger.info(f"[{self.node_id}] UNLIST: {asset_id} already mined by peer — discarding")
                return
            self.logger.warning(f"[{self.node_id}] UNLIST: aborted, peer mined different tx — retrying")
        self.logger.info(f"[{self.node_id}] UNLIST: mined asset_id={asset_id} nonce={block['nonce']} hash={block['hash'][:16]}...")
        self.send_gateway({
            "type": "ASSET_UNLIST_SIGNED_IN_BLOCKCHAIN",
            "data": {
                "block": block,
                "asset_id": asset_id,
                "owner": owner,
            },
            "sender_ip": self.advertised_ip(),
            "sender_port": self.port,
        })

    def handle_list_request(self, msg: dict[str, Any]):
        """Mine a LIST_ASSET tx for a previously-unlisted asset (re-listing it)."""
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        asset_id = str(data.get("asset_id", ""))
        owner = str(data.get("owner", ""))
        public_key = str(data.get("public_key", ""))
        signature = str(data.get("signature", ""))

        if not asset_id:
            self.logger.warning(f"[{self.node_id}] LIST_ASSET: missing asset_id, skipping")
            return

        tx = {
            "type": "LIST",
            "tx_id": str(data.get("tx_id") or f"list-{asset_id}-{int(time.time() * 1000)}"),
            "asset_id": asset_id,
            "user_public_key": public_key,
            "user_signature": signature,
            "timestamp": datetime.now().isoformat(),
        }

        self.logger.info(f"[{self.node_id}] LIST_ASSET: starting mining for asset_id={asset_id}")
        while True:
            block = self.mine(tx)
            if block is not None:
                break
            if self._node_stop_event.is_set():
                return
            if self._is_tx_in_chain(tx["tx_id"]):
                self.logger.info(f"[{self.node_id}] LIST_ASSET: {asset_id} already mined by peer — discarding")
                return
            self.logger.warning(f"[{self.node_id}] LIST_ASSET: aborted, peer mined different tx — retrying")
        self.logger.info(f"[{self.node_id}] LIST_ASSET: mined asset_id={asset_id} nonce={block['nonce']} hash={block['hash'][:16]}...")
        self.send_gateway({
            "type": "ASSET_LIST_SIGNED_IN_BLOCKCHAIN",
            "data": {
                "block": block,
                "asset_id": asset_id,
                "owner": owner,
            },
            "sender_ip": self.advertised_ip(),
            "sender_port": self.port,
        })

    def _validate_buy_tx(self, tx: dict):
        if not self.validate_tx(tx):
            sender = tx.get("sender", "")
            raise ValidationError(
                f"Insufficient balance: sender={sender[:12] if sender else '?'} "
                f"balance={self.get_balance(sender)} amount={tx.get('amount')}"
            )

    def handle_tx_request_buy(self, msg: dict[str, Any]):
        tx = self.tx_from_gateway_message(msg, "BUY")
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        asset_id = str(tx.get("asset_id") or data.get("asset_id") or "")
        try:
            self._validate_buy_tx(tx)
            if asset_id and self._is_double_buy(asset_id):
                raise ValidationError(f"Asset {asset_id} already purchased — double-buy rejected")
            self.pending_txs.append(tx)
            while True:
                block = self.mine(tx)
                if block is not None:
                    break
                if self._node_stop_event.is_set():
                    return
                # BUY abort: if this asset was purchased (by us or peer), stop; else retry
                if self._is_double_buy(asset_id) or self._is_tx_in_chain(tx["tx_id"]):
                    self.logger.info(f"[{self.node_id}] BUY: {asset_id} already purchased by peer — discarding")
                    return
                self.logger.warning(f"[{self.node_id}] BUY: aborted, peer mined different tx — retrying")
            self.notify_buy_success(tx)
            self.notify_gateway(block)
        except AurexError as e:
            self.logger.error(f"[{self.node_id}] BUY failed: {e}")
            self.send_gateway({
                "type": "BUY_FAILED",
                "data": {
                    "asset_id": asset_id,
                    "buyer": str(tx.get("buyer") or data.get("buyer") or ""),
                    "user_public_key": str(tx.get("user_public_key") or data.get("public_key") or ""),
                    "message": str(e),
                    "tx_id": str(tx.get("tx_id") or data.get("tx_id") or ""),
                },
            })

    def handle_tx_request_sell(self, msg: dict[str, Any]):
        tx = self.tx_from_gateway_message(msg, "SELL")
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
                self.persist_local_state()

    def _is_double_buy(self, asset_id: str) -> bool:
        """Return True if the asset is currently held (most recent tx is BUY, not LIST/MINT).

        A BUY followed by a LIST means the owner re-listed it — the next BUY must be allowed.
        We track the last ownership-changing tx and only block if it was a BUY.
        """
        last_relevant_type: str | None = None
        with self.lock:
            for b in self.chain:
                tx = b.get("tx", {}) if isinstance(b.get("tx"), dict) else {}
                if str(tx.get("asset_id") or "") != asset_id:
                    continue
                tx_type = str(tx.get("tx_type") or tx.get("type") or "").upper()
                if tx_type in ("BUY", "LIST", "ASSET_MINT"):
                    last_relevant_type = tx_type
        return last_relevant_type == "BUY"

    def handle_broadcast_tx_to_verify(self, msg: dict[str, Any]):
        sender_ip = str(msg.get("sender_ip") or "")
        sender_port = int(msg.get("sender_port") or 0)
        peer_label = f"{sender_ip}:{sender_port}"
        data = msg.get("data") if isinstance(msg.get("data"), dict) else {}
        publisher_chain_length = int(data.get("publisher_chain_length") or 0)
        block = data.get("block") if isinstance(data.get("block"), dict) else {}
        block_index = int(block.get("index", -1)) if block else -1
        my_len = len(self.chain)
        self.logger.info(f"[{self.node_id}] BROADCAST: verifying block index={block_index} from {peer_label} (their chain={publisher_chain_length}, ours={my_len})")
        # Primary chain-gap check: publisher explicitly told us they are ahead
        if publisher_chain_length > my_len + 1:
            self.logger.warning(f"[{self.node_id}] BROADCAST: chain gap — {peer_label} is at len={publisher_chain_length}, we are at {my_len}; stopping mine to sync")
            self._mining_stop_peer = peer_label
            self._mining_stop_event.set()
            self.ensure_local_state_or_fetch(sender_ip, sender_port, publisher_chain_length, str(data.get("userpk") or ""))
            return
        # Fallback: block index alone shows we are lagging (catches missing/zero publisher_chain_length)
        if block and block_index > my_len:
            effective_len = publisher_chain_length if publisher_chain_length > 0 else block_index + 1
            self.logger.warning(f"[{self.node_id}] BROADCAST: block index={block_index} is ahead of our chain len={my_len} — stopping mine to sync with {peer_label}")
            self._mining_stop_peer = peer_label
            self._mining_stop_event.set()
            self.ensure_local_state_or_fetch(sender_ip, sender_port, effective_len, str(data.get("userpk") or ""))
            return
        if block and block_index == my_len and str(block.get("prev_hash", "")) == self.last_hash():
            # Double-buy protection: if we already have a BUY for this asset (our own mined block),
            # the peer's BUY block is the canonical winner — sync from them to correct our chain.
            tx = block.get("tx", {}) if isinstance(block.get("tx"), dict) else {}
            tx_type = str(tx.get("tx_type") or tx.get("type") or "").upper()
            if tx_type == "BUY":
                asset_id = str(tx.get("asset_id") or "")
                if asset_id and self._is_double_buy(asset_id):
                    self.logger.warning(f"[{self.node_id}] BROADCAST: competing BUY for {asset_id} from {peer_label} — syncing chain from winner to fix balances")
                    self._mining_stop_peer = peer_label
                    self._mining_stop_event.set()
                    self.ensure_local_state_or_fetch(sender_ip, sender_port, publisher_chain_length, str(data.get("userpk") or ""), force=True)
                    return
            # Valid block received: abort current mining task and accept new chain state
            self.logger.info(f"[{self.node_id}] BROADCAST: verification complete — accepted block index={block_index} from {peer_label}, abandoning mine")
            self._mining_stop_peer = peer_label
            self._mining_stop_event.set()
            self.add_block(block)
            self.register_blockchain_node()
        else:
            # Stale block: index doesn't fit our chain or prev_hash doesn't match
            if block:
                self.logger.warning(f"[{self.node_id}] BROADCAST: verification failed — block index={block_index} doesn't fit our chain len={my_len} (stale/diverged block from {peer_label})")
            else:
                self.logger.warning(f"[{self.node_id}] BROADCAST: verification failed — no block in message from {peer_label}")

    # -------- peer ledger sharing --------

    def ensure_local_state_or_fetch(self, publisher_ip: str, publisher_port: int, publisher_chain_length: int = 0, userpk: str = "", force: bool = False):
        if not publisher_ip or not publisher_port:
            return
        ledger_missing = (not self.ledger_path.exists()) or (self.ledger_path.stat().st_size == 0)
        balances_missing = (not self.balances_path.exists()) or (self.balances_path.stat().st_size == 0)
        # > (not +1): a fresh node with 0 blocks vs publisher with 1 should always sync
        lagging = publisher_chain_length > len(self.chain)
        if force or ledger_missing or balances_missing or lagging:
            self.request_ledger_from_peer(publisher_ip, publisher_port)
            if userpk:
                self.request_balance_from_peer(publisher_ip, publisher_port, userpk)
            self.register_blockchain_node()

    def handle_get_ledger_sync(self, msg: dict[str, Any]):
        publisher_ip = str(msg.get("publisher_ip") or "")
        publisher_port = int(msg.get("publisher_port") or 0)
        publisher_chain_length = int(msg.get("publisher_chain_length") or 0)
        self.ensure_local_state_or_fetch(publisher_ip, publisher_port, publisher_chain_length, "")

    def handle_get_minted_ids(self, msg: dict[str, Any]):
        """Respond to gateway's GET_MINTED_IDS with all ASSET_MINT asset_ids from our chain."""
        _ = msg
        with self.lock:
            minted = [
                str(b["tx"].get("asset_id", ""))
                for b in self.chain
                if isinstance(b.get("tx"), dict)
                and str(b["tx"].get("type") or b["tx"].get("tx_type") or "").upper() == "ASSET_MINT"
            ]
        minted = [a for a in minted if a]
        self.send_gateway({
            "type": "MINTED_IDS",
            "data": {"asset_ids": minted},
        })
        self.logger.debug(f"[{self.node_id}] GET_MINTED_IDS: sent {len(minted)} minted id(s) to gateway")

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
                self.send_ledger_snapshot(comm)
            elif msg_type == "GET_BALANCE":
                userpk = str(msg.get("userpk") or "")
                comm.send_one_message(
                    {
                        "type": "BALANCE_RESPONSE",
                        "userpk": userpk,
                        "balance": self.get_balance(userpk),
                    }
                )

    def send_ledger_snapshot(self, comm):
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
                self.persist_local_state()

            self.logger.info(f"[{self.node_id}] ledger synced from {peer_ip}:{peer_port}")
            return True
        except Exception as exc:
            self.logger.warning(f"[{self.node_id}] ledger sync failed from {peer_ip}:{peer_port}: {exc}")
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
                self.persist_local_state()
            return True
        except Exception as exc:
            self.logger.warning(f"[{self.node_id}] balance sync failed from {peer_ip}:{peer_port}: {exc}")
            return False
        finally:
            try:
                client.close()
            except Exception:
                pass


if __name__ == "__main__":
    # Required on Windows: multiprocessing uses 'spawn', so the entry point must
    # be guarded so spawned worker processes don't re-run startup code.
    mp.freeze_support()

    parser = argparse.ArgumentParser(
        description="Aurex blockchain node. If --port is omitted, the OS will choose a free port."
    )
    parser.add_argument("--ip", type=str, default=BLOCKCHAIN_NODE_IP)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--difficulty", type=int, default=POW_DIFFICULTY)
    parser.add_argument(
        "--debug-level", "--DEBUG_LEVEL",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    from SharedResources.logging import Logger
    Logger.set_level(args.debug_level)

    if args.port == 0:
        print("[*] No --port provided. OS will assign a free port.")
    node = BlockchainNode(ip=args.ip, port=args.port, difficulty=args.difficulty)
    print(f"[*] Node initialized at {node.ip}:{node.port}")
    print(f"[*] Node keys directory: {node.node_keys_dir}")
    node.start()
