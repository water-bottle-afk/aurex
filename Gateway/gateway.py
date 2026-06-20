"""
gateway.py — the Aurex gateway server.

Sits between the marketplace server and the blockchain nodes.  Its job is to:
  - relay buy/sell/upload/unlist requests from the server to all nodes
  - validate mined blocks before broadcasting them to the rest of the network
  - deduplicate transactions so the same tx can't be mined twice
  - route balance queries to the node with the longest chain
  - run a UDP server so nodes can discover the gateway by broadcast

The gateway itself holds no wallet and writes no user data — it is purely a
routing and validation layer.
"""
__author__ = "Nadav"

import os
import sys
import threading
import time
import logging
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

# Adds the root folder to enable imports from SharedResources
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from SharedResources.classes import RSA_Client, RSA_Server, UDPServer
from SharedResources.config import (
    GATEWAY_UDP_PORT,
    GATEWAY_IP,
    SERVER_IP,
    SERVER_PORT,
    GATEWAY_BLOCKCHAIN_PORT,
)
from SharedResources.exceptions import (
    AurexError,
    ValidationError,
    DuplicateError,
    BlockchainError,
)


class GatewayServer:
    """Single gateway runtime: server<->nodes transparent relay with lightweight routing."""

    def __init__(self):
        self.logger = logging.getLogger("gateway")
        self.logger.setLevel(logging.INFO)

        self.base_dir = Path(__file__).resolve().parent
        self.keys_dir = self.base_dir / "GatewayKeys"
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        self.stop_event = threading.Event()

        self.node_listener = RSA_Server(
            GATEWAY_IP,
            GATEWAY_BLOCKCHAIN_PORT,
            dir_for_keys=str(self.keys_dir),
            name="GatewayNodeServer",
        )
        self.node_listener.handle_client = self.handle_node_connection

        self.server_client = RSA_Client(SERVER_IP, SERVER_PORT, name="GatewayToServer")
        self.server_client.communicate_with_server = self.communicate_with_main_server

        self.udp_service = UDPServer("0.0.0.0", GATEWAY_UDP_PORT, GATEWAY_IP, GATEWAY_BLOCKCHAIN_PORT)

        self.nodes_lock = threading.Lock()
        self.nodes: dict[tuple[str, int], dict[str, Any]] = {}

        # TX_ID dedup cache — prevents the same transaction from being processed twice.
        self.seen_tx_ids: set[str] = set()
        # Asset-level mint dedup — populated in-memory from node on startup (no local file).
        self.seen_minted_asset_ids: set[str] = set()

        self.gateway_operations = {
            "buy_asset": self.tx_request_buy,
            "sell_asset": self.tx_request_sell,
            "publish_tx": self.broadcast_tx_to_verify,
            "tx_request_buy": self.tx_request_buy,
            "tx_request_sell": self.tx_request_sell,
            "get_balance": self.handle_get_balance,
            "create_balance": self.create_balance,
            "upload_asset": self.handle_upload_asset,
            "unlist_asset": self.handle_unlist_asset_from_server,
            "list_asset": self.handle_list_asset_from_server,
        }
        self.blockchain_operations = {
            "register_blockchain_node": self.register_blockchain_node,
            "tx_request_buy": self.tx_request_buy,
            "tx_request_sell": self.tx_request_sell,
            "broadcast_tx_to_verify": self.broadcast_tx_to_verify,
            "get_balance": self.handle_get_balance,
            "buy_success": self.notify_buy_success,
            "sell_success": self.notify_sell_success,
            "send_balance": self.notify_send_balance,
            "asset_signed_in_blockchain": self.handle_asset_signed_in_blockchain,
            "asset_unlist_signed_in_blockchain": self.handle_asset_unlist_signed_in_blockchain,
            "asset_list_signed_in_blockchain": self.handle_asset_list_signed_in_blockchain,
            "minted_ids": self.handle_minted_ids_response,
        }

    def start(self):
        """Start all gateway services: UDP discovery, server relay, node listener."""
        threading.Thread(target=self.udp_service.run, daemon=True).start()
        threading.Thread(target=self._server_connect_loop, daemon=True).start()
        threading.Thread(target=self.node_listener.start, daemon=True).start()

        self.log_event("Gateway operational. Routing between nodes and server.")
        while not self.stop_event.is_set():
            time.sleep(0.2)

    def _server_connect_loop(self):
        """Connect to the server and retry indefinitely on failure or disconnect.

        Creates a fresh RSA_Client for each attempt because the socket is bound
        on construction and cannot be reused after a failed connect().
        """
        while not self.stop_event.is_set():
            try:
                client = RSA_Client(SERVER_IP, SERVER_PORT, name="GatewayToServer")
                client.communicate_with_server = self.communicate_with_main_server
                self.server_client = client
                self.log_event("Connecting to server...")
                client.start()  # blocks until server disconnects; raises on connection failure
                self.log_event("Server connection closed — reconnecting in 5s")
            except Exception as exc:
                self.log_event(f"Server connection failed ({exc}) — retrying in 5s")
            if not self.stop_event.is_set():
                time.sleep(5)

    def stop(self):
        self.stop_event.set()

    def log_event(self, message: str, **_extra):
        self.logger.info(message)

    def normalize_type(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def handle_minted_ids_response(self, request: dict, comm=None):
        """Merge asset_ids from a node's MINTED_IDS response into seen_minted_asset_ids."""
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        ids = data.get("asset_ids")
        if isinstance(ids, list):
            new_ids = {str(a) for a in ids if a}
            added = new_ids - self.seen_minted_asset_ids
            if added:
                self.seen_minted_asset_ids.update(added)
                self.log_event(f"Synced {len(added)} minted asset_id(s) from node", status="info")

    def extract_sender_addr(self, comm):
        try:
            ip, port = comm.sock.getpeername()
            return str(ip), int(port)
        except Exception:
            return "", 0

    def register_comm(self, ip: str, port: int, comm, chain_length: int = 0):
        if not ip or not port:
            return
        with self.nodes_lock:
            prev_registered = bool(self.nodes.get((ip, int(port)), {}).get("registered"))
            self.nodes[(ip, int(port))] = {
                "comm": comm,
                "chain_length": int(chain_length),
                "registered": prev_registered,
                # Explicit P2P (node-to-node) address — distinct from the ephemeral gateway connection port
                "p2p_ip": ip,
                "p2p_port": int(port),
            }

    def best_node_addr(self) -> "tuple[str, int] | None":
        """
        Return the P2P address of the node with the longest known chain.

        Used when routing ``GET_BALANCE`` requests — only the most up-to-date
        node is queried so clients receive a single, consistent balance value
        rather than one response per node.

        Returns:
            (p2p_ip, p2p_port) tuple, or None if no nodes are connected.
        """
        with self.nodes_lock:
            if not self.nodes:
                return None
            return max(self.nodes.keys(), key=lambda a: int(self.nodes[a].get("chain_length", 0)))

    def send_to_node(self, addr: "tuple[str, int]", msg: dict) -> bool:
        with self.nodes_lock:
            info = self.nodes.get(addr)
        if not info:
            return False
        comm = info.get("comm")
        if not comm:
            return False
        try:
            comm.send_one_message(msg)
            return True
        except Exception as exc:
            self.log_event(f"Node send failed {addr[0]}:{addr[1]}: {exc}", status="warning")
            return False

    def update_node_length(self, addr: tuple[str, int], chain_length: int):
        with self.nodes_lock:
            if addr in self.nodes:
                self.nodes[addr]["chain_length"] = int(chain_length)

    def remove_comm(self, comm):
        with self.nodes_lock:
            dead = [node_addr for node_addr, info in self.nodes.items() if info.get("comm") == comm]
            for node_addr in dead:
                self.nodes.pop(node_addr, None)

    def route_to_server(self, msg: dict):
        if not self.server_client.communication:
            self.log_event("Main server connection unavailable", status="warning")
            return
        self.server_client.communication.send_one_message(msg)

    def broadcast_to_nodes(self, msg: dict, skip_addr: tuple[str, int] | None = None):
        with self.nodes_lock:
            targets = [(addr, info.get("comm")) for addr, info in self.nodes.items()]

        seen_comm_ids: set[int] = set()
        for addr, node_comm in targets:
            if skip_addr and addr == skip_addr:
                continue
            if node_comm is None:
                continue
            # Dedup: the same physical connection can appear under both its
            # ephemeral TCP port and its registered P2P port.  Only send once.
            comm_id = id(node_comm)
            if comm_id in seen_comm_ids:
                continue
            seen_comm_ids.add(comm_id)
            try:
                node_comm.send_one_message(msg)
            except Exception as exc:
                self.log_event(f"Node send failed {addr[0]}:{addr[1]}: {exc}", status="warning")

    def canonical_json_bytes(self, payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def verify_user_signature(self, public_key_hex: str, payload: dict[str, Any], signature_hex: str) -> bool:
        try:
            pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(public_key_hex))
            pub.verify(bytes.fromhex(signature_hex), self.canonical_json_bytes(payload), ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    def verify_block(self, block: dict[str, Any], label: str = "") -> tuple[bool, str]:
        """Validate a mined block: hash integrity, PoW target, and ECDSA signature if present.

        Chain continuity (index / prev_hash) is intentionally not checked here —
        that is the exclusive responsibility of the nodes during PoW consensus.
        Returns (True, block_hash) on success, (False, reason) on failure.
        """
        if not isinstance(block, dict):
            return False, f"[{label}] block is not a dict"

        tx = block.get("tx")
        if not isinstance(tx, dict):
            tx = block.get("transaction") if isinstance(block.get("transaction"), dict) else {}

        # Only BUY transactions need gateway-level user-signature verification.
        # MINT / LIST / UNLIST are server-initiated: the server already validated
        # the user's signature before forwarding to the node, so there is no
        # canonical payload for the gateway to reconstruct here.
        # PoW hash integrity (checked below) is sufficient for those tx types.
        tx_type = str(tx.get("type") or tx.get("tx_type") or "").upper()
        if tx_type == "BUY":
            signature_hex  = str(tx.get("user_signature") or tx.get("signature") or "")
            public_key_hex = str(tx.get("user_public_key") or tx.get("public_key") or "")
            if signature_hex and public_key_hex:
                signed_payload: dict = {
                    "asset_id":  tx.get("asset_id"),
                    "buyer":     tx.get("buyer"),
                    "price":     tx.get("price"),
                    "timestamp": tx.get("timestamp"),
                }
                if not self.verify_user_signature(public_key_hex, signed_payload, signature_hex):
                    return False, f"[{label}] invalid user signature"

        block_copy = {k: v for k, v in block.items() if k != "hash"}
        block_hash = str(block.get("hash", ""))
        recomputed = hashlib.sha256(self.canonical_json_bytes(block_copy)).hexdigest()
        if block_hash and block_hash != recomputed:
            return False, f"[{label}] hash mismatch"

        difficulty = int(block.get("difficulty", 0) or 0)
        if difficulty > 0 and not recomputed.startswith("0" * difficulty):
            return False, f"[{label}] PoW invalid nonce={block.get('nonce')} hash={recomputed[:16]}..."

        block["hash"] = recomputed
        return True, recomputed

    def maybe_sync_lagging_nodes(self, publisher_addr: tuple[str, int], publisher_chain_length: int, userpk: str):
        if publisher_chain_length <= 0:
            return
        threshold = int(publisher_chain_length) - 1
        with self.nodes_lock:
            snapshot = [(addr, info.copy()) for addr, info in self.nodes.items()]

        for addr, info in snapshot:
            if addr == publisher_addr:
                continue
            node_len = int(info.get("chain_length", 0) or 0)
            if node_len > threshold:
                continue
            comm = info.get("comm")
            if comm is None:
                continue
            try:
                comm.send_one_message(
                    {
                        "type": "GET_LEDGER",
                        "publisher_ip": publisher_addr[0],
                        "publisher_port": publisher_addr[1],
                        "publisher_chain_length": int(publisher_chain_length),
                    }
                )
                comm.send_one_message(
                    {
                        "type": "GET_BALANCE",
                        "publisher_ip": publisher_addr[0],
                        "publisher_port": publisher_addr[1],
                        "publisher_chain_length": int(publisher_chain_length),
                        "userpk": userpk,
                    }
                )
            except Exception as exc:
                self.log_event(f"Sync request failed for {addr[0]}:{addr[1]}: {exc}", status="warning")

    def handle_node_connection(self, comm):
        ip, port = self.extract_sender_addr(comm)
        self.register_comm(ip, port, comm, chain_length=0)

        try:
            while True:
                request = comm.recv_one_message()
                if not request:
                    break
                self.handle_node_message(comm, request)
        finally:
            registered_id = None
            with self.nodes_lock:
                for node_addr, info in self.nodes.items():
                    if info.get("comm") == comm and info.get("registered"):
                        registered_id = f"{node_addr[0]}:{node_addr[1]}"
                        break
            self.remove_comm(comm)
            if registered_id:
                self.log_event(
                    f"Node disconnected {registered_id}",
                    event_type="node_status",
                    direction="system",
                    status="disconnected",
                    node_id=registered_id,
                    address=registered_id,
                )

    def handle_node_message(self, comm, request: dict):
        msg_type = self.normalize_type(request.get("type"))
        handler = self.blockchain_operations.get(msg_type)

        if handler:
            handler(request, comm=comm)
            return

        self.route_to_server(request)
        self.log_event(
            f"Routed node message to server: {request.get('type')}",
            event_type="route",
            direction="outbound",
        )

    def communicate_with_main_server(self):
        comm = self.server_client.communication
        self.communicate_with_main_server_comm(comm)

    # Server acknowledgement types that require no further action.
    SERVER_ACK_TYPES = frozenset({
        "ok", "ready",
        "gateway_registered",
        "buy_acknowledged", "buy_failed_acknowledged",
        "sell_acknowledged",
        "balance_acknowledged",
        "block_rejected_acknowledged",
        "fully_upload_acknowledged",
        "unlist_acknowledged",
        "move_pending", "unlist_pending",
        "balance_requested", "key_updated",
    })

    def communicate_with_main_server_comm(self, comm):
        # announce ourselves so the server knows a gateway is online
        try:
            comm.send_one_message({"type": "REGISTER_GATEWAY"})
        except Exception:
            pass

        while True:
            request = comm.recv_one_message()
            if not request:
                break   # server disconnected

            msg_type = self.normalize_type(request.get("type"))

            # skip routine ack messages — nothing to do with them
            if msg_type in self.SERVER_ACK_TYPES:
                continue

            if msg_type == "error":
                self.log_event(f"Server error message: {request.get('message')}", status="warning")
                continue

            handler = self.gateway_operations.get(msg_type)
            if handler:
                # message handled by gateway logic (balance, tx routing, etc.)
                handler(request)
                self.log_event(
                    f"Processed request from server: {request.get('type')}",
                    event_type="route",
                    direction="inbound",
                )
            else:
                # unknown type — forward blindly to all nodes
                self.broadcast_to_nodes(request)
                self.log_event(
                    f"Forwarded server message to nodes: {request.get('type')}",
                    event_type="route",
                    direction="outbound",
                )

    def register_blockchain_node(self, request: dict, comm=None):
        """
        Register a newly connected blockchain node in ``self.nodes``.

        Extracts the node's P2P server address (``node_server_ip``,
        ``node_server_port``) from the message data.  This address is stored as
        the dict key and used in sync messages (GET_LEDGER / GET_BALANCE) so
        other nodes know where to connect for peer-to-peer sync.

        If the registering node's chain is shorter than the current best node's
        chain, a ``GET_LEDGER`` message is immediately sent to it pointing at
        the best node, triggering an automatic ledger sync.

        Args:
            request: REGISTER_BLOCKCHAIN_NODE message from the node.
            comm:    The node's gateway communication object.
        """
        ip, port = self.extract_sender_addr(comm) if comm else ("", 0)
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        # reg_ip:reg_port = the node's P2P server address (for node-to-node sync).
        # Prefer node_server_ip/node_server_port set explicitly by Bnode, fall back to
        # legacy "ip"/"port" fields, then to sender_ip/sender_port from the message, then
        # to the raw TCP connection source address (ephemeral — last resort only).
        reg_ip = str(data.get("node_server_ip") or data.get("ip") or request.get("sender_ip") or ip)
        reg_port = int(data.get("node_server_port") or data.get("port") or request.get("sender_port") or port or 0)
        chain_length = int(data.get("chain_length") or request.get("chain_length") or 0)

        if comm:
            # Remove stale ephemeral-port entries for this comm before inserting
            # the canonical P2P address so broadcast_to_nodes never sends twice
            # to the same socket.
            with self.nodes_lock:
                stale = [
                    addr for addr, info in self.nodes.items()
                    if info.get("comm") is comm and addr != (reg_ip, reg_port)
                ]
                for addr in stale:
                    self.nodes.pop(addr, None)
            self.register_comm(reg_ip, reg_port, comm, chain_length=chain_length)
            with self.nodes_lock:
                self.nodes[(reg_ip, reg_port)]["registered"] = True

        self.log_event(
            f"Registered blockchain node {reg_ip}:{reg_port} len={chain_length}",
            event_type="node_status",
            direction="inbound",
            status="connected",
            node_id=f"{reg_ip}:{reg_port}",
            address=f"{reg_ip}:{reg_port}",
        )

        # Ask every registering node for its minted asset IDs so seen_minted_asset_ids
        # stays accurate without any local ledger file (stateless gateway).
        if comm:
            try:
                comm.send_one_message({"type": "GET_MINTED_IDS"})
            except Exception:
                pass

        # If this node's chain is shorter than the current best, tell it to sync immediately
        if comm and reg_ip and reg_port:
            best = self.best_node_addr()
            if best and best != (reg_ip, reg_port):
                with self.nodes_lock:
                    best_len = int(self.nodes[best].get("chain_length", 0))
                if chain_length < best_len:
                    try:
                        comm.send_one_message({
                            "type": "GET_LEDGER",
                            "publisher_ip": best[0],
                            "publisher_port": best[1],
                            "publisher_chain_length": best_len,
                        })
                        self.log_event(
                            f"Told new node {reg_ip}:{reg_port} to sync from {best[0]}:{best[1]} (len={best_len})",
                            status="info",
                        )
                    except Exception:
                        pass

    def check_tx_id(self, data: dict, label: str) -> bool:
        """
        Deduplicate incoming transactions by their client-generated TX_ID.

        The first time a TX_ID is seen it is added to ``self.seen_tx_ids`` and
        the function returns False (not a duplicate — proceed).  On subsequent
        calls with the same TX_ID it returns True (duplicate — reject).

        This prevents double-execution when a network retry or two near-
        simultaneous users submit the same transaction.

        Args:
            data:  Message data dict that may contain a ``tx_id`` key.
            label: Human-readable label used in the warning log entry.

        Returns:
            True  — duplicate, caller should reject the transaction.
            False — first-time seen, caller should process it.
        """
        tx_id = str(data.get("tx_id") or "")
        if not tx_id:
            return False
        if tx_id in self.seen_tx_ids:
            self.log_event(f"TX_DUPLICATE rejected: {label} tx_id={tx_id[:20]}...", status="warning")
            return True
        self.seen_tx_ids.add(tx_id)
        return False

    def tx_request_buy(self, request: dict, comm=None):
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else request
        if self.check_tx_id(data, "BUY"):
            buyer = str(data.get("buyer") or "")
            asset_id = str(data.get("asset_id") or "")
            self.route_to_server({
                "type": "BUY_FAILED",
                "data": {"buyer": buyer, "asset_id": asset_id, "message": "TX_DUPLICATE — transaction already submitted"},
            })
            return
        outbound = {
            "type": "TX_REQUEST_BUY",
            "data": data,
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self.broadcast_to_nodes(outbound)

    def tx_request_sell(self, request: dict, comm=None):
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else request
        if self.check_tx_id(data, "SELL"):
            return
        outbound = {
            "type": "TX_REQUEST_SELL",
            "data": data,
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self.broadcast_to_nodes(outbound)

    # ── Fail-fast guards ──────────────────────────────────────────────────────

    def _require_block(self, block: dict, label: str):
        if not block:
            raise BlockchainError(f"[{label}] missing block in message")

    def _require_asset_id(self, asset_id: str, label: str):
        if not asset_id:
            raise ValidationError(f"[{label}] missing asset_id")

    def _verify_and_get_hash(self, block: dict, label: str) -> str:
        ok, result = self.verify_block(block, label)
        if not ok:
            raise BlockchainError(result)
        return result

    def _guard_duplicate_mint(self, asset_id: str):
        if asset_id in self.seen_minted_asset_ids:
            raise DuplicateError(f"asset_id={asset_id} already in minted set")

    def _broadcast_verified_block(self, block: dict, sender_ip: str, sender_port: int):
        skip = (sender_ip, sender_port) if sender_ip and sender_port else None
        self.broadcast_to_nodes({
            "type": "BROADCAST_TX_TO_VERIFY",
            "data": {"block": block, "publisher_chain_length": 0},
            "sender_ip": sender_ip,
            "sender_port": sender_port,
        }, skip_addr=skip)

    def _reject_duplicate_tx(self, data: dict, label: str, owner: str, asset_id: str) -> bool:
        """Return True and notify server if this tx_id was already seen."""
        if not self.check_tx_id(data, label):
            return False
        self.route_to_server({
            "type": "BLOCK_REJECTED",
            "data": {
                "asset_id": asset_id, "owner": owner, "username": owner,
                "message": "Duplicate transaction — this upload was already submitted",
                "reason": "TX_DUPLICATE",
            },
        })
        return True

    def _reject_already_minted(self, asset_id: str, owner: str) -> bool:
        """Return True and notify server if this asset was already minted."""
        if not asset_id or asset_id not in self.seen_minted_asset_ids:
            return False
        self.log_event(f"[ASSET_MINT] duplicate rejected: asset_id={asset_id} already minted")
        self.route_to_server({
            "type": "BLOCK_REJECTED",
            "data": {
                "asset_id": asset_id, "owner": owner, "username": owner,
                "message": f"Asset {asset_id} is already minted on the blockchain",
                "reason": "DUPLICATE_MINT",
            },
        })
        self.route_to_server({"type": "FULLY_UPLOAD", "asset_id": asset_id, "block_hash": ""})
        return True

    # ── Gateway-operation handlers ────────────────────────────────────────────

    def handle_upload_asset(self, request: dict, comm=None):
        """Dedup-check a mint request then broadcast to nodes."""
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        owner = str(data.get("owner") or "")
        asset_id = str(data.get("asset_id") or "")

        if self._reject_duplicate_tx(data, "UPLOAD_ASSET", owner, asset_id):
            return
        if self._reject_already_minted(asset_id, owner):
            return

        self.broadcast_to_nodes(request)

    def handle_unlist_asset_from_server(self, request: dict, comm=None):
        """Server requests unlist mining — dedup check then broadcast to nodes."""
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        if self.check_tx_id(data, "UNLIST_ASSET"):
            return
        self.broadcast_to_nodes(request)

    def handle_list_asset_from_server(self, request: dict, comm=None):
        """Server requests re-list mining (UNLISTED → LISTED) — dedup then broadcast."""
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        if self.check_tx_id(data, "LIST_ASSET"):
            return
        self.broadcast_to_nodes(request)

    def handle_asset_list_signed_in_blockchain(self, request: dict, comm=None):
        """Handle a LIST_ASSET block mined by a node — verify, append, route FULLY_UPLOAD."""
        _ = comm
        try:
            sender_ip = str(request.get("sender_ip") or "")
            sender_port = int(request.get("sender_port") or 0)
            data = request.get("data") if isinstance(request.get("data"), dict) else {}
            block = data.get("block") if isinstance(data.get("block"), dict) else {}
            asset_id = str(data.get("asset_id", ""))
            self._require_block(block, "LIST_ASSET")
            self._require_asset_id(asset_id, "LIST_ASSET")
            block_hash = self._verify_and_get_hash(block, "LIST_ASSET")
            self.log_event(f"[LIST_ASSET] verified asset={asset_id} hash={block_hash[:16]}...")
            self._broadcast_verified_block(block, sender_ip, sender_port)
            self.route_to_server({"type": "FULLY_UPLOAD", "asset_id": asset_id, "block_hash": block_hash})
        except AurexError as e:
            self.log_event(f"[LIST_ASSET] rejected: {e}")

    def broadcast_tx_to_verify(self, request: dict, comm=None):
        """
        Validate a mined block from a node and broadcast it to all other nodes.

        Steps:
          1. Calls ``verify_block`` — checks hash, PoW, and ECDSA signature.
          2. If valid: updates the publisher node's chain-length and broadcasts
             ``BROADCAST_TX_TO_VERIFY`` to every other node so they can stop
             mining and add the block.
          3. Calls ``maybe_sync_lagging_nodes`` to push ``GET_LEDGER`` to any
             nodes whose chain length is behind the publisher's.

        Args:
            request: Raw message from the publishing node.
            comm:    The publisher node's communication object (for address extraction).
        """
        try:
            sender_ip, sender_port = self.extract_sender_addr(comm) if comm else ("", 0)
            publisher_addr = (request.get("sender_ip") or sender_ip, int(request.get("sender_port") or sender_port or 0))
            req_data = request.get("data") if isinstance(request.get("data"), dict) else {}
            block = req_data.get("block") if isinstance(req_data.get("block"), dict) else req_data
            publisher_chain_length = int(req_data.get("publisher_chain_length") or request.get("publisher_chain_length") or 0)
            self._require_block(block, "BROADCAST_TX")
            self._verify_and_get_hash(block, "BROADCAST_TX")
            self.update_node_length(publisher_addr, publisher_chain_length)
            tx = block.get("tx") if isinstance(block.get("tx"), dict) else {}
            userpk = str(tx.get("user_public_key") or tx.get("sender") or "")
            self.maybe_sync_lagging_nodes(publisher_addr, publisher_chain_length, userpk)
            self.broadcast_to_nodes({
                "type": "BROADCAST_TX_TO_VERIFY",
                "data": {"block": block, "publisher_chain_length": publisher_chain_length},
                "sender_ip": publisher_addr[0],
                "sender_port": publisher_addr[1],
            }, skip_addr=publisher_addr)
        except AurexError as e:
            self.log_event(f"Rejected block: {e}")

    def handle_get_balance(self, request: dict, comm=None):
        _ = comm
        userpk = request.get("userpk")
        if not userpk and isinstance(request.get("data"), dict):
            userpk = request["data"].get("userpk")

        outbound = {
            "type": "GET_BALANCE",
            "userpk": userpk,
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        # Only ask the node with the longest chain — prevents duplicate BALANCE_IS
        # responses from multiple nodes with stale/divergent balances.
        best = self.best_node_addr()
        if best:
            self.send_to_node(best, outbound)
        else:
            self.broadcast_to_nodes(outbound)

    def notify_buy_success(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "buy_success",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self.route_to_server(payload)

    def notify_sell_success(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "sell_success",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self.route_to_server(payload)

    def notify_send_balance(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "send_balance",
            "data": request.get("data", request),
            "userpk": request.get("userpk"),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self.route_to_server(payload)

    def handle_asset_signed_in_blockchain(self, request: dict, comm=None):
        """
        Handle an ASSET_MINT block that a node successfully mined.

        Validates the block's hash and PoW, appends it to the gateway ledger,
        broadcasts ``BROADCAST_TX_TO_VERIFY`` to all other nodes so they stop
        their parallel mining subprocesses, then tells the server to mark the
        asset as ``MINTED`` or ``LISTED`` via ``FULLY_UPLOAD``.

        Args:
            request: Message from the mining node containing the mined block,
                     asset_id, and owner username.
            comm:    Sender's communication object (unused — sender info is
                     read from request fields).
        """
        _ = comm
        try:
            sender_ip = str(request.get("sender_ip") or "")
            sender_port = int(request.get("sender_port") or 0)
            data = request.get("data") if isinstance(request.get("data"), dict) else {}
            block = data.get("block") if isinstance(data.get("block"), dict) else {}
            asset_id = str(data.get("asset_id", ""))
            self._require_block(block, "ASSET_MINT")
            self._require_asset_id(asset_id, "ASSET_MINT")
            block_hash = self._verify_and_get_hash(block, "ASSET_MINT")
            self._guard_duplicate_mint(asset_id)
            self.seen_minted_asset_ids.add(asset_id)
            self.log_event(f"[ASSET_MINT] verified asset={asset_id} hash={block_hash[:16]}...")
            self._broadcast_verified_block(block, sender_ip, sender_port)
            self.route_to_server({"type": "FULLY_UPLOAD", "asset_id": asset_id, "block_hash": block_hash})
        except AurexError as e:
            self.log_event(f"[ASSET_MINT] rejected: {e}")

    def handle_asset_unlist_signed_in_blockchain(self, request: dict, comm=None):
        _ = comm
        try:
            sender_ip = str(request.get("sender_ip") or "")
            sender_port = int(request.get("sender_port") or 0)
            data = request.get("data") if isinstance(request.get("data"), dict) else {}
            block = data.get("block") if isinstance(data.get("block"), dict) else {}
            asset_id = str(data.get("asset_id", ""))
            owner = str(data.get("owner", ""))
            self._require_block(block, "UNLIST")
            self._require_asset_id(asset_id, "UNLIST")
            block_hash = self._verify_and_get_hash(block, "UNLIST")
            self.log_event(f"[UNLIST] verified asset={asset_id} hash={block_hash[:16]}...")
            self._broadcast_verified_block(block, sender_ip, sender_port)
            self.route_to_server({"type": "ASSET_UNLISTED", "asset_id": asset_id, "block_hash": block_hash, "owner": owner})
        except AurexError as e:
            self.log_event(f"[UNLIST] rejected: {e}")

    def create_balance(self, request: dict, comm=None):
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else request
        outbound = {
            "type": "CREATE_BALANCE",
            "username": data.get("username"),
            "public_key": data.get("public_key"),
            "balance": data.get("balance"),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self.broadcast_to_nodes(outbound)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    GatewayServer().start()


if __name__ == "__main__":
    main()
