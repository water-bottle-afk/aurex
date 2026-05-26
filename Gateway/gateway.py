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
from SharedResources.logging import Logger


class GatewayServer:
    """Single gateway runtime: server<->nodes transparent relay with lightweight routing."""

    def __init__(self, gui_bridge=None):
        self.logger = Logger("gateway")

        self.base_dir = Path(__file__).resolve().parent
        self.keys_dir = self.base_dir / "GatewayKeys"
        self.keys_dir.mkdir(parents=True, exist_ok=True)

        self.gui_bridge = gui_bridge
        self.stop_event = threading.Event()

        self.node_listener = RSA_Server(
            GATEWAY_IP,
            GATEWAY_BLOCKCHAIN_PORT,
            dir_for_keys=str(self.keys_dir),
            name="GatewayNodeServer",
            peer_label="Bnode",
        )
        self.node_listener.handle_client = self.handle_node_connection

        self.server_client = RSA_Client(SERVER_IP, SERVER_PORT, name="GatewayToServer", peer_label="Server")
        self.server_client.communicate_with_server = self.communicate_with_main_server

        self.udp_service = UDPServer(GATEWAY_IP, GATEWAY_UDP_PORT, GATEWAY_IP, GATEWAY_BLOCKCHAIN_PORT)

        self.nodes_lock = threading.Lock()
        self.nodes: dict[tuple[str, int], dict[str, Any]] = {}

        self.gateway_operations = {
            "BUY_ASSET": self.tx_request_buy,
            "SELL_ASSET": self.tx_request_sell,
            "PUBLISH_TX": self.broadcast_tx_to_verify,
            "TX_REQUEST_BUY": self.tx_request_buy,
            "TX_REQUEST_SELL": self.tx_request_sell,
            "GET_BALANCE": self.handle_get_balance,
            "CREATE_BALANCE": self.create_balance,
            "UNLIST_ASSET": self.handle_unlist_to_nodes,
            "UPLOAD_ASSET": self.upload_asset_to_nodes,
        }
        self.blockchain_operations = {
            "REGISTER_BLOCKCHAIN_NODE": self.register_blockchain_node,
            "TX_REQUEST_BUY": self.tx_request_buy,
            "TX_REQUEST_SELL": self.tx_request_sell,
            "BROADCAST_TX_TO_VERIFY": self.broadcast_tx_to_verify,
            "GET_BALANCE": self.handle_get_balance,
            "BUY_SUCCESS": self.notify_buy_success,
            "SELL_SUCCESS": self.notify_sell_success,
            "SEND_BALANCE": self.notify_send_balance,
            "ASSET_SIGNED_IN_BLOCKCHAIN": self.handle_asset_signed_in_blockchain,
            "ASSET_UNLIST_SIGNED_IN_BLOCKCHAIN": self.handle_asset_unlist_signed_in_blockchain,
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
        return str(value or "").strip().upper()

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
            }

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
        """Validate a block by verifying its signature and PoW. No ledger state required."""
        if not isinstance(block, dict):
            return False, "block is not dict"

        tx = block.get("tx")
        if not isinstance(tx, dict):
            tx = block.get("transaction") if isinstance(block.get("transaction"), dict) else {}

        signature_hex = str(block.get("signature") or tx.get("signature") or "")
        public_key_hex = str(block.get("public_key") or tx.get("public_key") or "")

        if signature_hex and public_key_hex:
            payload = tx.get("data") if isinstance(tx.get("data"), dict) else tx
            if not self._verify_user_signature(public_key_hex, payload, signature_hex):
                return False, "invalid user signature"

        block_for_hash = {k: v for k, v in block.items() if k != "hash"}
        block_hash = str(block.get("hash", ""))
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
        "OK", "READY",
        "GATEWAY_REGISTERED",
        "BUY_ACKNOWLEDGED", "BUY_FAILED_ACKNOWLEDGED",
        "SELL_ACKNOWLEDGED",
        "BALANCE_ACKNOWLEDGED",
        "BLOCK_REJECTED_ACKNOWLEDGED",
        "FULLY_UPLOAD_ACKNOWLEDGED",
        "UNLIST_ACKNOWLEDGED",
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
            if msg_type == "ERROR":
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
        reg_ip = str(data.get("ip") or request.get("sender_ip") or ip)
        reg_port = int(data.get("port") or request.get("sender_port") or port or 0)
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

    def tx_request_buy(self, request: dict, comm=None):
        _ = comm
        outbound = {
            "type": "TX_REQUEST_BUY",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._broadcast_to_nodes(outbound)

    def tx_request_sell(self, request: dict, comm=None):
        _ = comm
        outbound = {
            "type": "TX_REQUEST_SELL",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._broadcast_to_nodes(outbound)

    def broadcast_tx_to_verify(self, request: dict, comm=None):
        sender_ip, sender_port = self._extract_sender_addr(comm) if comm else ("", 0)
        publisher_addr = (request.get("sender_ip") or sender_ip, int(request.get("sender_port") or sender_port or 0))

        req_data = request.get("data") if isinstance(request.get("data"), dict) else {}
        block = req_data.get("block") if isinstance(req_data.get("block"), dict) else req_data
        publisher_chain_length = int(req_data.get("publisher_chain_length") or request.get("publisher_chain_length") or 0)

        ok, reason = self._validate_block(block)
        if not ok:
            self.log_event(f"Rejected block: {reason}", status="warning")
            return

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
        self._broadcast_to_nodes(outbound)

    def notify_buy_success(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "BUY_SUCCESS",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._route_to_server(payload)

    def notify_sell_success(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "SELL_SUCCESS",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._route_to_server(payload)

    def notify_send_balance(self, request: dict, comm=None):
        _ = comm
        payload = {
            "type": "SEND_BALANCE",
            "data": request.get("data", request),
            "userpk": request.get("userpk"),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._route_to_server(payload)

    def handle_asset_signed_in_blockchain(self, request: dict, comm=None):
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        block = data.get("block") if isinstance(data.get("block"), dict) else {}
        asset_id = str(data.get("asset_id", ""))

        if not block or not asset_id:
            self.log_event("[ASSET_MINT] missing block or asset_id", status="warning")
            return

        ok, reason = self._validate_block(block)
        if not ok:
            self.log_event(f"[ASSET_MINT] block invalid for asset {asset_id}: {reason}", status="warning")
            return

        block_hash = str(block.get("hash", ""))
        self.log_event(f"[ASSET_MINT] block verified for asset {asset_id}, hash={block_hash[:16]}...")
        self._route_to_server({
            "type": "FULLY_UPLOAD",
            "asset_id": asset_id,
            "block_hash": block_hash,
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

    def upload_asset_to_nodes(self, request: dict, comm=None):
        """Forward UPLOAD_ASSET request from server to all nodes for PoW minting."""
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else request
        asset_id = str(data.get("asset_id", "?"))
        outbound = {
            "type": "UPLOAD_ASSET",
            "data": data,
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._broadcast_to_nodes(outbound)
        self.log_event(
            f"Broadcasted UPLOAD_ASSET to nodes for asset {asset_id}",
            event_type="route",
            direction="outbound",
        )

    def handle_unlist_to_nodes(self, request: dict, comm=None):
        """Forward UNLIST_ASSET request from server to all nodes for mining."""
        _ = comm
        outbound = {
            "type": "UNLIST_ASSET",
            "data": request.get("data", request),
            "sender_ip": request.get("sender_ip"),
            "sender_port": request.get("sender_port"),
        }
        self._broadcast_to_nodes(outbound)

    def handle_asset_unlist_signed_in_blockchain(self, request: dict, comm=None):
        """Validate UNLIST_ASSET_FROM_BLOCKCHAIN block from node and notify server."""
        _ = comm
        data = request.get("data") if isinstance(request.get("data"), dict) else {}
        block = data.get("block") if isinstance(data.get("block"), dict) else {}
        asset_id = str(data.get("asset_id", ""))

        if not block or not asset_id:
            self.log_event("[UNLIST] missing block or asset_id", status="warning")
            return

        ok, reason = self._validate_block(block)
        if not ok:
            self.log_event(f"[UNLIST] block invalid for asset {asset_id}: {reason}", status="warning")
            return

        block_hash = str(block.get("hash", ""))
        self.log_event(f"[UNLIST] block verified for asset {asset_id}, hash={block_hash[:16]}...")
        self._route_to_server({
            "type": "ASSET_UNLISTED",
            "asset_id": asset_id,
            "block_hash": block_hash,
        })


def main():
    import argparse
    _parser = argparse.ArgumentParser(description="Aurex gateway")
    _parser.add_argument(
        "--debug-level", "--DEBUG_LEVEL",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    _args, _ = _parser.parse_known_args()
    Logger.set_level(_args.debug_level)

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
