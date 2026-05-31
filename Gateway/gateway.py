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


class GatewayServer:
    """Single gateway runtime: server<->nodes transparent relay with lightweight routing."""

    def __init__(self, gui_bridge=None):
        self.logger = logging.getLogger("gateway")
        self.logger.setLevel(logging.INFO)

        self.base_dir = Path(__file__).resolve().parent
        self.keys_dir = self.base_dir / "GatewayKeys"
        self.keys_dir.mkdir(parents=True, exist_ok=True)

        self.ledger_path = self.base_dir / "gateway_ledger.json"

        self.gui_bridge = gui_bridge
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

        self.gateway_ledger: list[dict[str, Any]] = self._load_gateway_ledger()

        # TX_ID dedup cache — prevents the same transaction from being processed twice.
        self.seen_tx_ids: set[str] = set()

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
        }

    def start(self):
        threading.Thread(target=self.udp_service.run, daemon=True).start()
        threading.Thread(target=self.server_client.start, daemon=True).start()
        threading.Thread(target=self.node_listener.start, daemon=True).start()

        self.log_event("Gateway operational. Routing between nodes and server.")
        while not self.stop_event.is_set():
            time.sleep(0.2)

    def stop(self):
        self.stop_event.set()

    def log_event(self, message: str, event_type: str = "log", direction: str = "system", status: str = "info", **extra):
        self.logger.info(message)
        if self.gui_bridge is None:
            return
        try:
            self.gui_bridge.log_event(
                node_id=extra.pop("node_id", "gateway"),
                message=message,
                event_type=event_type,
                direction=direction,
                status=status,
                timestamp=extra.pop("timestamp", datetime.now().strftime("%H:%M:%S")),
                **extra,
            )
        except Exception:
            pass

    def _normalize_type(self, value: Any) -> str:
        return str(value or "").strip().lower()

    def _load_gateway_ledger(self):
        if not self.ledger_path.exists():
            self.ledger_path.write_text("[]", encoding="utf-8")
            return []
        try:
            raw = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, list) else []
        except Exception:
            return []

    def _save_gateway_ledger(self):
        self.ledger_path.write_text(json.dumps(self.gateway_ledger, ensure_ascii=False, indent=2), encoding="utf-8")

    def _extract_sender_addr(self, comm):
        try:
            ip, port = comm.sock.getpeername()
            return str(ip), int(port)
        except Exception:
            return "", 0

    def _register_comm(self, ip: str, port: int, comm, chain_length: int = 0):
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

    def _best_node_addr(self) -> "tuple[str, int] | None":
        """Return the (p2p_ip, p2p_port) of the node with the longest chain."""
        with self.nodes_lock:
            if not self.nodes:
                return None
            return max(self.nodes.keys(), key=lambda a: int(self.nodes[a].get("chain_length", 0)))

    def _send_to_node(self, addr: "tuple[str, int]", msg: dict) -> bool:
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

    def _update_node_length(self, addr: tuple[str, int], chain_length: int):
        with self.nodes_lock:
            if addr in self.nodes:
                self.nodes[addr]["chain_length"] = int(chain_length)

    def _remove_comm(self, comm):
        with self.nodes_lock:
            dead = [node_addr for node_addr, info in self.nodes.items() if info.get("comm") == comm]
            for node_addr in dead:
                self.nodes.pop(node_addr, None)

    def _route_to_server(self, msg: dict):
        if not self.server_client.communication:
            self.log_event("Main server connection unavailable", status="warning")
            return
        self.server_client.communication.send_one_message(msg)

    def _broadcast_to_nodes(self, msg: dict, skip_addr: tuple[str, int] | None = None):
        with self.nodes_lock:
            targets = [(addr, info.get("comm")) for addr, info in self.nodes.items()]

        for addr, node_comm in targets:
            if skip_addr and addr == skip_addr:
                continue
            if node_comm is None:
                continue
            try:
                node_comm.send_one_message(msg)
            except Exception as exc:
                self.log_event(f"Node send failed {addr[0]}:{addr[1]}: {exc}", status="warning")

    def _canonical_json_bytes(self, payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")

    def _verify_user_signature(self, public_key_hex: str, payload: dict[str, Any], signature_hex: str) -> bool:
        try:
            pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(public_key_hex))
            pub.verify(bytes.fromhex(signature_hex), self._canonical_json_bytes(payload), ec.ECDSA(hashes.SHA256()))
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    def _validate_block(self, block: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(block, dict):
            return False, "block is not dict"

        index = int(block.get("index", -1))
        expected_index = len(self.gateway_ledger)
        if index != expected_index:
            return False, f"block index mismatch expected={expected_index} got={index}"

        prev_hash = str(block.get("prev_hash", ""))
        expected_prev_hash = "0" * 64 if not self.gateway_ledger else str(self.gateway_ledger[-1].get("hash", ""))
        if prev_hash != expected_prev_hash:
            return False, "prev_hash mismatch"

        tx = block.get("tx")
        if not isinstance(tx, dict):
            tx = block.get("transaction") if isinstance(block.get("transaction"), dict) else {}

        signature_hex = str(block.get("signature") or tx.get("signature") or "")
        public_key_hex = str(block.get("public_key") or tx.get("public_key") or "")

        payload = tx.get("data") if isinstance(tx.get("data"), dict) else tx
        if not signature_hex or not public_key_hex:
            return False, "missing signature/public_key"
        if not self._verify_user_signature(public_key_hex, payload, signature_hex):
            return False, "invalid user signature"

        block_for_hash = dict(block)
        block_hash = str(block_for_hash.pop("hash", ""))
        recomputed = hashlib.sha256(self._canonical_json_bytes(block_for_hash)).hexdigest()
        if block_hash and block_hash != recomputed:
            return False, "block hash mismatch"

        difficulty = int(block.get("difficulty", 0) or 0)
        if difficulty > 0 and not recomputed.startswith("0" * difficulty):
            return False, "invalid PoW target"

        block["hash"] = recomputed
        return True, "ok"

    def _maybe_sync_lagging_nodes(self, publisher_addr: tuple[str, int], publisher_chain_length: int, userpk: str):
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
        ip, port = self._extract_sender_addr(comm)
        self._register_comm(ip, port, comm, chain_length=0)

        try:
            while True:
                request = comm.recv_one_message()
                if not request:
                    break
                self._handle_node_message(comm, request)
        finally:
            registered_id = None
            with self.nodes_lock:
                for node_addr, info in self.nodes.items():
                    if info.get("comm") == comm and info.get("registered"):
                        registered_id = f"{node_addr[0]}:{node_addr[1]}"
                        break
            self._remove_comm(comm)
            if registered_id:
                self.log_event(
                    f"Node disconnected {registered_id}",
                    event_type="node_status",
                    direction="system",
                    status="disconnected",
                    node_id=registered_id,
                    address=registered_id,
                )

    def _handle_node_message(self, comm, request: dict):
        msg_type = self._normalize_type(request.get("type"))
        handler = self.blockchain_operations.get(msg_type)

        if handler:
            handler(request, comm=comm)
            return

        self._route_to_server(request)
        self.log_event(
            f"Routed node message to server: {request.get('type')}",
            event_type="route",
            direction="outbound",
        )

    def communicate_with_main_server(self):
        comm = self.server_client.communication
        self._communicate_with_main_server_comm(comm)

    # Server acknowledgement types that require no further action.
    _SERVER_ACK_TYPES = frozenset({
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

    def _communicate_with_main_server_comm(self, comm):
        try:
            comm.send_one_message({"type": "REGISTER_GATEWAY"})
        except Exception:
            pass
        while True:
            request = comm.recv_one_message()
            if not request:
                break

            msg_type = self._normalize_type(request.get("type"))
            if msg_type in self._SERVER_ACK_TYPES:
                continue
            if msg_type == "error":
                self.log_event(f"Server error message: {request.get('message')}", status="warning")
                continue
            handler = self.gateway_operations.get(msg_type)
            if handler:
                handler(request)
                self.log_event(
                    f"Processed request from server: {request.get('type')}",
                    event_type="route",
                    direction="inbound",
                )
            else:
                self._broadcast_to_nodes(request)
                self.log_event(
                    f"Forwarded server message to nodes: {request.get('type')}",
                    event_type="route",
                    direction="outbound",
                )

    def register_blockchain_node(self, request: dict, comm=None):
        ip, port = self._extract_sender_addr(comm) if comm else ("", 0)
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        # reg_ip:reg_port = the node's P2P server address (for node-to-node sync).
        # Prefer node_server_ip/node_server_port set explicitly by Bnode, fall back to
        # legacy "ip"/"port" fields, then to sender_ip/sender_port from the message, then
        # to the raw TCP connection source address (ephemeral — last resort only).
        reg_ip = str(data.get("node_server_ip") or data.get("ip") or request.get("sender_ip") or ip)
        reg_port = int(data.get("node_server_port") or data.get("port") or request.get("sender_port") or port or 0)
        chain_length = int(data.get("chain_length") or request.get("chain_length") or 0)

        if comm:
            self._register_comm(reg_ip, reg_port, comm, chain_length=chain_length)
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

        # If this node's chain is shorter than the current best, tell it to sync immediately
        if comm and reg_ip and reg_port:
            best = self._best_node_addr()
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

    def _check_tx_id(self, data: dict, label: str) -> bool:
        """Returns True if tx_id is a duplicate (should be rejected)."""
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
        if self._check_tx_id(data, "BUY"):
            buyer = str(data.get("buyer") or "")
            asset_id = str(data.get("asset_id") or "")
            self._route_to_server({
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
        self._broadcast_to_nodes(outbound)

    def tx_request_sell(self, request: dict, comm=None):
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else request
        if self._check_tx_id(data, "SELL"):
            return
        outbound = {
            "type": "TX_REQUEST_SELL",
            "data": data,
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._broadcast_to_nodes(outbound)

    def handle_upload_asset(self, request: dict, comm=None):
        """Server requests asset mining — dedup check then broadcast to nodes."""
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        if self._check_tx_id(data, "UPLOAD_ASSET"):
            return
        self._broadcast_to_nodes(request)

    def handle_unlist_asset_from_server(self, request: dict, comm=None):
        """Server requests unlist mining — dedup check then broadcast to nodes."""
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        if self._check_tx_id(data, "UNLIST_ASSET"):
            return
        self._broadcast_to_nodes(request)

    def broadcast_tx_to_verify(self, request: dict, comm=None):
        sender_ip, sender_port = self._extract_sender_addr(comm) if comm else ("", 0)
        publisher_addr = (request.get("sender_ip") or sender_ip, int(request.get("sender_port") or sender_port or 0))

        req_data = request.get("data") if isinstance(request.get("data"), dict) else {}
        block = req_data.get("block") if isinstance(req_data.get("block"), dict) else req_data
        publisher_chain_length = int(req_data.get("publisher_chain_length") or request.get("publisher_chain_length") or len(self.gateway_ledger) + 1)

        ok, reason = self._validate_block(block)
        if not ok:
            self.log_event(f"Rejected block: {reason}", status="warning")
            return

        self.gateway_ledger.append(block)
        self._save_gateway_ledger()
        self._update_node_length((publisher_addr[0], publisher_addr[1]), publisher_chain_length)

        tx = block.get("tx") if isinstance(block.get("tx"), dict) else (block.get("transaction") if isinstance(block.get("transaction"), dict) else {})
        userpk = str(tx.get("sender") or "")
        self._maybe_sync_lagging_nodes((publisher_addr[0], publisher_addr[1]), publisher_chain_length, userpk)

        outbound = {
            "type": "BROADCAST_TX_TO_VERIFY",
            "data": {
                "block": block,
                "publisher_chain_length": publisher_chain_length,
            },
            "sender_ip": publisher_addr[0],
            "sender_port": publisher_addr[1],
        }
        self._broadcast_to_nodes(outbound, skip_addr=(publisher_addr[0], publisher_addr[1]))

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
        best = self._best_node_addr()
        if best:
            self._send_to_node(best, outbound)
        else:
            self._broadcast_to_nodes(outbound)

    def notify_buy_success(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "buy_success",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._route_to_server(payload)

    def notify_sell_success(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "sell_success",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._route_to_server(payload)

    def notify_send_balance(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "send_balance",
            "data": request.get("data", request),
            "userpk": request.get("userpk"),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._route_to_server(payload)

    def _verify_mined_block(self, block: dict, label: str) -> tuple[bool, str]:
        """Shared PoW + hash validation for ASSET_MINT and UNLIST blocks."""
        block_copy = {k: v for k, v in block.items() if k != "hash"}
        block_hash = str(block.get("hash", ""))
        recomputed = hashlib.sha256(
            json.dumps(block_copy, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        difficulty = int(block.get("difficulty", 0) or 0)
        if block_hash != recomputed:
            return False, f"[{label}] hash mismatch: got {block_hash[:16]}... expected {recomputed[:16]}..."
        if difficulty > 0 and not recomputed.startswith("0" * difficulty):
            return False, f"[{label}] PoW invalid nonce={block.get('nonce')} hash={block_hash[:16]}..."
        block["hash"] = recomputed
        return True, block_hash

    def handle_asset_signed_in_blockchain(self, request: dict, comm=None):
        sender_ip = str(request.get("sender_ip") or "")
        sender_port = int(request.get("sender_port") or 0)
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        block = data.get("block") if isinstance(data.get("block"), dict) else {}
        asset_id = str(data.get("asset_id", ""))

        if not block or not asset_id:
            self.log_event("[ASSET_MINT] missing block or asset_id", status="warning")
            return

        ok, result = self._verify_mined_block(block, "ASSET_MINT")
        if not ok:
            self.log_event(result, status="warning")
            return

        block_hash = result
        self.log_event(f"[ASSET_MINT] verified asset={asset_id} nonce={block.get('nonce')} hash={block_hash[:16]}...")
        self.gateway_ledger.append(block)
        self._save_gateway_ledger()

        # Stop other nodes that are still mining this asset
        skip = (sender_ip, sender_port) if sender_ip and sender_port else None
        self._broadcast_to_nodes({
            "type": "BROADCAST_TX_TO_VERIFY",
            "data": {"block": block, "publisher_chain_length": len(self.gateway_ledger)},
            "sender_ip": sender_ip,
            "sender_port": sender_port,
        }, skip_addr=skip)

        self._route_to_server({
            "type": "FULLY_UPLOAD",
            "asset_id": asset_id,
            "block_hash": block_hash,
        })

    def handle_asset_unlist_signed_in_blockchain(self, request: dict, comm=None):
        sender_ip = str(request.get("sender_ip") or "")
        sender_port = int(request.get("sender_port") or 0)
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        block = data.get("block") if isinstance(data.get("block"), dict) else {}
        asset_id = str(data.get("asset_id", ""))
        owner = str(data.get("owner", ""))

        if not block or not asset_id:
            self.log_event("[UNLIST] missing block or asset_id", status="warning")
            return

        ok, result = self._verify_mined_block(block, "UNLIST")
        if not ok:
            self.log_event(result, status="warning")
            return

        block_hash = result
        self.log_event(f"[UNLIST] verified asset={asset_id} nonce={block.get('nonce')} hash={block_hash[:16]}...")
        self.gateway_ledger.append(block)
        self._save_gateway_ledger()

        # Stop other nodes that are still mining this unlist
        skip = (sender_ip, sender_port) if sender_ip and sender_port else None
        self._broadcast_to_nodes({
            "type": "BROADCAST_TX_TO_VERIFY",
            "data": {"block": block, "publisher_chain_length": len(self.gateway_ledger)},
            "sender_ip": sender_ip,
            "sender_port": sender_port,
        }, skip_addr=skip)

        self._route_to_server({
            "type": "ASSET_UNLISTED",
            "asset_id": asset_id,
            "block_hash": block_hash,
            "owner": owner,
        })

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
        self._broadcast_to_nodes(outbound)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    gateway_server = GatewayServer()

    answer = input("Use gateway GUI dashboard? (y/n): ").strip().lower()
    if answer in {"y", "yes"}:
        from Gateway.gateway_dashboard import run_dashboard

        threading.Thread(target=gateway_server.start, daemon=True).start()
        run_dashboard(gateway_server)
        return

    gateway_server.start()


if __name__ == "__main__":
    main()
