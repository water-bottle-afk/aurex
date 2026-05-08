"""Aurex modular entry points for encrypted Gateway and Blockchain Nodes."""

from __future__ import annotations

import argparse
import socket
import threading
import time
from pathlib import Path
from typing import Any

from aurex_logging import AurexLogger

try:
    from .blockchain_logic import Block, BlockchainEngine, SignedTransaction
    from .networking import (
        AUREX_DISCOVERY_PORT,
        DiscoveryResponder,
        EncryptedClient,
        EncryptedServer,
        build_protocol_message,
        discover_gateway,
        validate_protocol_message,
    )
except ImportError:
    from blockchain_logic import Block, BlockchainEngine, SignedTransaction
    from networking import (
        AUREX_DISCOVERY_PORT,
        DiscoveryResponder,
        EncryptedClient,
        EncryptedServer,
        build_protocol_message,
        discover_gateway,
        validate_protocol_message,
    )

logger = AurexLogger.get_logger(__name__)


class GatewayNodeRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._nodes: dict[str, dict[str, Any]] = {}

    def upsert(self, node_id: str, ip: str, listener_port: int, ledger_length: int) -> None:
        now = time.time()
        with self._lock:
            self._nodes[node_id] = {
                "ip": ip,
                "listener_port": int(listener_port),
                "ledger_length": int(ledger_length),
                "last_seen": now,
            }

    def all(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {k: dict(v) for k, v in self._nodes.items()}

    def update_length(self, node_id: str, ledger_length: int) -> None:
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id]["ledger_length"] = int(ledger_length)
                self._nodes[node_id]["last_seen"] = time.time()


class AurexGatewayApp:
    """Encrypted gateway with UDP discovery and node broadcast fanout."""

    def __init__(
        self,
        *,
        host: str = "0.0.0.0",
        port: int = 5000,
        key_dir: str | Path = "keys",
        notify_server_host: str = "127.0.0.1",
        notify_server_port: int = 23457,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.notify_server_host = notify_server_host
        self.notify_server_port = int(notify_server_port)
        self.registry = GatewayNodeRegistry()
        self.discovery = DiscoveryResponder(self.host, self.port, port=AUREX_DISCOVERY_PORT)
        self.encrypted_server = EncryptedServer(
            self.host,
            self.port,
            key_dir=key_dir,
            key_name="aurex_gateway",
            timeout=10,
        )
        self.running = False

    def start(self) -> None:
        self.running = True
        self.encrypted_server.bind_and_listen()
        threading.Thread(target=self.discovery.serve_forever, daemon=True).start()
        logger.info("AurexGateway listening on %s:%s", self.host, self.port)
        while self.running:
            try:
                client, addr, aes_key = self.encrypted_server.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    logger.exception("gateway accept failed")
                continue
            threading.Thread(target=self._handle_connection, args=(client, addr, aes_key), daemon=True).start()

    def _handle_connection(self, client, addr, aes_key: bytes) -> None:
        try:
            message = self.encrypted_server.recv_json(client, aes_key)
            ok, reason = validate_protocol_message(message)
            if not ok:
                self.encrypted_server.send_json(
                    client,
                    aes_key,
                    build_protocol_message("ERROR", {"reason": reason}),
                )
                return
            msg_type = message["type"]
            payload = message["payload"]
            if msg_type == "NODE_REGISTER":
                self._handle_node_register(payload, addr)
                self.encrypted_server.send_json(
                    client,
                    aes_key,
                    build_protocol_message("REGISTERED", {"nodes": self.registry.all()}),
                )
                return
            if msg_type == "POW_FOUND":
                response = self._handle_pow_found(payload)
                self.encrypted_server.send_json(client, aes_key, response)
                return
            if msg_type == "NODE_HEARTBEAT":
                self._handle_node_register(payload, addr)
                self.encrypted_server.send_json(client, aes_key, build_protocol_message("OK", {"alive": True}))
                return
            if msg_type == "SUBMIT_TRANSACTION":
                response = self._handle_submit_transaction(payload)
                self.encrypted_server.send_json(client, aes_key, response)
                return
            self.encrypted_server.send_json(
                client,
                aes_key,
                build_protocol_message("ERROR", {"reason": f"unknown type {msg_type}"}),
            )
        except Exception as exc:
            logger.warning("gateway handle error from %s: %s", addr, exc)
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _handle_node_register(self, payload: dict[str, Any], addr: tuple[str, int]) -> None:
        node_id = str(payload.get("node_id") or f"node_{addr[1]}")
        ip = str(payload.get("ip") or addr[0])
        listener_port = int(payload.get("listener_port") or 0)
        ledger_length = int(payload.get("ledger_length") or 0)
        self.registry.upsert(node_id, ip, listener_port, ledger_length)
        logger.info("node registered: %s %s:%s len=%s", node_id, ip, listener_port, ledger_length)

    def _handle_pow_found(self, payload: dict[str, Any]) -> dict[str, Any]:
        node_id = str(payload.get("node_id") or "")
        answer = int(payload.get("answer") or 0)
        sender_ip = str(payload.get("ip") or "")
        listener_port = int(payload.get("listener_port") or 0)
        ledger_length = int(payload.get("ledger_length") or 0)
        latest_block = payload.get("latest_block") if isinstance(payload.get("latest_block"), dict) else None

        self.registry.upsert(node_id, sender_ip, listener_port, ledger_length)
        fanout_payload = {
            "answer": answer,
            "ledger_length": ledger_length,
            "ip": sender_ip,
            "listener_port": listener_port,
            "node_id": node_id,
            "latest_block": latest_block or {},
        }
        self._broadcast_to_nodes(build_protocol_message("POW_NOTIFICATION", fanout_payload))
        self._notify_server(build_protocol_message("BLOCK_MINED", fanout_payload))
        return build_protocol_message("POW_BROADCASTED", {"nodes": len(self.registry.all())})

    def _broadcast_to_nodes(self, message: dict[str, Any]) -> None:
        nodes = self.registry.all()
        for node_id, info in nodes.items():
            ip = str(info.get("ip") or "")
            listener_port = int(info.get("listener_port") or 0)
            if not ip or not listener_port:
                continue
            try:
                EncryptedClient(ip, listener_port, timeout=5.0).request(message, expect_response=False)
            except Exception as exc:
                logger.debug("broadcast to %s failed: %s", node_id, exc)

    def _handle_submit_transaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        tx = payload.get("transaction") if isinstance(payload.get("transaction"), dict) else {}
        if not tx:
            return build_protocol_message("TX_SUBMIT_RESULT", {"ok": False, "reason": "missing transaction"})
        relay_message = build_protocol_message("NEW_TRANSACTION", {"transaction": tx})
        accepted = 0
        total = 0
        for node_id, info in self.registry.all().items():
            ip = str(info.get("ip") or "")
            listener_port = int(info.get("listener_port") or 0)
            if not ip or not listener_port:
                continue
            total += 1
            try:
                response = EncryptedClient(ip, listener_port, timeout=5.0).request(relay_message, expect_response=True)
                if response and response.get("type") == "TX_RESULT":
                    result_payload = response.get("payload") or {}
                    if bool(result_payload.get("ok")):
                        accepted += 1
                        self.registry.update_length(
                            node_id,
                            int(info.get("ledger_length") or 0),
                        )
            except Exception as exc:
                logger.debug("submit tx relay failed to %s: %s", node_id, exc)
        return build_protocol_message(
            "TX_SUBMIT_RESULT",
            {"ok": accepted > 0, "accepted_nodes": accepted, "total_nodes": total},
        )

    def _notify_server(self, message: dict[str, Any]) -> None:
        try:
            EncryptedClient(self.notify_server_host, self.notify_server_port, timeout=5.0).request(
                message,
                expect_response=False,
            )
        except Exception as exc:
            logger.debug("gateway->server notify failed: %s", exc)

    def stop(self) -> None:
        self.running = False
        self.discovery.close()
        self.encrypted_server.close()


class AurexNodeApp:
    """Encrypted blockchain node with dual-socket logic and pull-based ledger sync."""

    def __init__(
        self,
        *,
        node_id: str,
        host: str = "0.0.0.0",
        listener_port: int = 13245,
        gateway_host: str | None = None,
        gateway_port: int = 5000,
        difficulty: int = 3,
        base_dir: str | Path = "BLOCKCHAIN_DB",
    ) -> None:
        self.node_id = node_id
        self.host = host
        self.listener_port = int(listener_port)
        self.gateway_host = gateway_host
        self.gateway_port = int(gateway_port)
        self.running = False
        node_dir = Path(base_dir) / self.node_id
        node_dir.mkdir(parents=True, exist_ok=True)
        self.engine = BlockchainEngine(
            ledger_path=node_dir / "ledger.json",
            state_path=node_dir / "state.pickle",
            difficulty=difficulty,
        )
        self.listener = EncryptedServer(
            self.host,
            self.listener_port,
            key_dir="keys",
            key_name=f"{self.node_id}_listener",
            timeout=10,
        )

    def start(self) -> None:
        self.running = True
        if not self.gateway_host:
            discovered = discover_gateway(timeout=3.0)
            if discovered:
                self.gateway_host, self.gateway_port = discovered
        if not self.gateway_host:
            raise RuntimeError("gateway not found (discovery failed and no host provided)")

        self.listener.bind_and_listen()
        threading.Thread(target=self._listen_loop, daemon=True).start()
        self._register_with_gateway()
        logger.info(
            "%s started listener=%s:%s gateway=%s:%s",
            self.node_id,
            self.host,
            self.listener_port,
            self.gateway_host,
            self.gateway_port,
        )

    def _listen_loop(self) -> None:
        while self.running:
            try:
                client, _addr, aes_key = self.listener.accept()
                threading.Thread(target=self._handle_incoming, args=(client, aes_key), daemon=True).start()
            except socket.timeout:
                continue
            except OSError:
                if self.running:
                    logger.exception("%s listener accept failed", self.node_id)
                continue

    def _handle_incoming(self, client, aes_key: bytes) -> None:
        try:
            message = self.listener.recv_json(client, aes_key)
            ok, reason = validate_protocol_message(message)
            if not ok:
                self.listener.send_json(client, aes_key, build_protocol_message("ERROR", {"reason": reason}))
                return
            msg_type = message["type"]
            payload = message["payload"]
            if msg_type == "LEDGER_REQUEST":
                response = build_protocol_message(
                    "LEDGER_RESPONSE",
                    {
                        "ledger": self.engine.export_ledger(),
                        "state": dict(self.engine.state_store.state),
                        "ledger_length": self.engine.ledger_length,
                    },
                )
                self.listener.send_json(client, aes_key, response)
                return
            if msg_type == "POW_NOTIFICATION":
                self._handle_pow_notification(payload)
                self.listener.send_json(client, aes_key, build_protocol_message("OK", {"handled": True}))
                return
            if msg_type == "NEW_TRANSACTION":
                tx = SignedTransaction.from_dict(payload.get("transaction") or {})
                added, reason = self.engine.add_transaction(tx)
                self.listener.send_json(client, aes_key, build_protocol_message("TX_RESULT", {"ok": added, "reason": reason}))
                return
            self.listener.send_json(client, aes_key, build_protocol_message("ERROR", {"reason": "unsupported message"}))
        except Exception as exc:
            logger.debug("%s incoming handler error: %s", self.node_id, exc)
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _register_with_gateway(self) -> None:
        payload = {
            "node_id": self.node_id,
            "ip": self._advertised_ip(),
            "listener_port": self.listener_port,
            "ledger_length": self.engine.ledger_length,
        }
        message = build_protocol_message("NODE_REGISTER", payload)
        EncryptedClient(self.gateway_host, self.gateway_port, timeout=8.0).request(message, expect_response=True)

    def _advertised_ip(self) -> str:
        if self.host in ("127.0.0.1", "localhost"):
            return "127.0.0.1"
        if self.host not in ("0.0.0.0",):
            return self.host
        try:
            import socket

            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("8.8.8.8", 80))
                return probe.getsockname()[0]
        except OSError:
            return "127.0.0.1"

    def submit_transaction(self, transaction: SignedTransaction) -> tuple[bool, str]:
        return self.engine.add_transaction(transaction)

    def mine_once(self) -> bool:
        block = self.engine.mine_pending_block()
        if block is None:
            return False
        ok, reason = self.engine.add_block(block)
        if not ok:
            logger.warning("%s mined block rejected locally: %s", self.node_id, reason)
            return False
        self._notify_gateway_pow_found(block)
        return True

    def _notify_gateway_pow_found(self, block: Block) -> None:
        payload = {
            "node_id": self.node_id,
            "answer": block.nonce,
            "ledger_length": self.engine.ledger_length,
            "ip": self._advertised_ip(),
            "listener_port": self.listener_port,
            "latest_block": block.to_dict(),
        }
        message = build_protocol_message("POW_FOUND", payload)
        EncryptedClient(self.gateway_host, self.gateway_port, timeout=8.0).request(message, expect_response=True)

    def _handle_pow_notification(self, payload: dict[str, Any]) -> None:
        sender_ip = str(payload.get("ip") or "")
        sender_port = int(payload.get("listener_port") or 0)
        sender_length = int(payload.get("ledger_length") or 0)
        latest_block_data = payload.get("latest_block") if isinstance(payload.get("latest_block"), dict) else None

        # First: validate and append announced block if it's the next one.
        if latest_block_data:
            block = Block.from_dict(latest_block_data)
            if block.index == self.engine.latest_block.index + 1:
                ok, _reason = self.engine.add_block(block)
                if ok:
                    logger.info("%s accepted broadcast block index=%s", self.node_id, block.index)

        # Then: if sender chain is longer, pull full ledger from sender listener.
        if sender_length > self.engine.ledger_length and sender_ip and sender_port:
            self._sync_from_peer(sender_ip, sender_port)

    def _sync_from_peer(self, peer_ip: str, peer_port: int) -> None:
        request = build_protocol_message("LEDGER_REQUEST", {"node_id": self.node_id})
        try:
            response = EncryptedClient(peer_ip, peer_port, timeout=10.0).request(request, expect_response=True)
            if not response:
                return
            if response.get("type") != "LEDGER_RESPONSE":
                return
            payload = response.get("payload") or {}
            remote_ledger = payload.get("ledger") if isinstance(payload.get("ledger"), list) else []
            remote_state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
            if len(remote_ledger) <= self.engine.ledger_length:
                return
            ok, reason = self.engine.import_full_ledger(remote_ledger, remote_state)
            if ok:
                logger.info("%s synced full ledger from %s:%s", self.node_id, peer_ip, peer_port)
            else:
                logger.warning("%s rejected remote ledger sync: %s", self.node_id, reason)
        except Exception as exc:
            logger.debug("%s sync from peer failed: %s", self.node_id, exc)

    def stop(self) -> None:
        self.running = False
        self.listener.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Aurex encrypted modular app")
    sub = parser.add_subparsers(dest="role", required=True)

    gw = sub.add_parser("gateway", help="Run encrypted gateway")
    gw.add_argument("--host", default="0.0.0.0")
    gw.add_argument("--port", type=int, default=5000)
    gw.add_argument("--notify-host", default="127.0.0.1")
    gw.add_argument("--notify-port", type=int, default=23457)

    node = sub.add_parser("node", help="Run encrypted blockchain node")
    node.add_argument("--node-id", required=True)
    node.add_argument("--host", default="0.0.0.0")
    node.add_argument("--listener-port", type=int, required=True)
    node.add_argument("--gateway-host", default="")
    node.add_argument("--gateway-port", type=int, default=5000)
    node.add_argument("--difficulty", type=int, default=3)
    node.add_argument("--mine", action="store_true", help="Mine once immediately if pending tx exists")

    args = parser.parse_args()
    if args.role == "gateway":
        app = AurexGatewayApp(
            host=args.host,
            port=args.port,
            notify_server_host=args.notify_host,
            notify_server_port=args.notify_port,
        )
        try:
            app.start()
        except KeyboardInterrupt:
            app.stop()
        return

    app = AurexNodeApp(
        node_id=args.node_id,
        host=args.host,
        listener_port=args.listener_port,
        gateway_host=args.gateway_host or None,
        gateway_port=args.gateway_port,
        difficulty=args.difficulty,
    )
    app.start()
    if args.mine:
        app.mine_once()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        app.stop()


if __name__ == "__main__":
    main()
