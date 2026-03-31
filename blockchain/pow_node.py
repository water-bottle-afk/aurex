"""
PoW Node - Proof of Work blockchain node with P2P gossip and multiprocessing miner.
- Main thread/listener: P2P, mempool, block validation, SQLite writes.
- Mining process: dedicated SHA-256 hashing loop; stopped by multiprocessing.Event when peer wins.
"""

import socket
import json
import hashlib
import time
import threading
import multiprocessing
import logging
import struct
from datetime import datetime, timezone
import sys
import os
import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519

sys.path.insert(0, os.path.dirname(__file__))

from key_manager import NodeKeyManager
from classes import Ledger, Block, Transaction
from config import (
    NODE_PORTS,
    RPC_HOST,
    RPC_PORT,
    DEFAULT_SOCKET_TIMEOUT,
    TX_TIME_WINDOW_SECONDS,
    ENFORCE_MINER_ALLOWLIST,
    ALLOWED_MINER_KEY_FINGERPRINTS,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('pow_node')


def _canonical_tx_message(sender, data):
    payload = {"sender": sender, "data": data}
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()


def _verify_ed25519_signature(public_key_b64, message_bytes, signature_b64):
    try:
        public_key_raw = base64.b64decode(public_key_b64.encode())
        signature_raw = base64.b64decode(signature_b64.encode())
        public_key = ed25519.Ed25519PublicKey.from_public_bytes(public_key_raw)
        public_key.verify(signature_raw, message_bytes)
        return True
    except Exception:
        return False


def _fingerprint_public_key(public_key_pem):
    return hashlib.sha256(public_key_pem.encode()).hexdigest()


def hashing_process(data, difficulty, stop_event, result_queue):
    """
    CPU-bound mining loop. Runs in a separate process.
    Exits when stop_event is set (peer found block) or when nonce is found.
    """
    nonce = 0
    target = '0' * difficulty
    while not stop_event.is_set():
        hash_attempt = hashlib.sha256(f"{data}{nonce}".encode()).hexdigest()
        if hash_attempt.startswith(target):
            result_queue.put((hash_attempt, nonce))
            return
        nonce += 1
    # stopped by peer block (no log in subprocess to avoid cross-process logger issues)


class PoWNode:
    """
    Proof of Work Node: listener (main thread) + mining (multiprocessing).
    Each node has its own ledger JSON in blockchain/BLOCKCHAIN_DB.
    """

    def __init__(self, host='0.0.0.0', port=11111, difficulty=2, gateway_host=None, gateway_port=None):
        self.node_id = f"node_{port}"
        self.host = host
        self.port = port
        self.difficulty = difficulty
        self.gateway_host = gateway_host if gateway_host is not None else RPC_HOST
        self.gateway_port = int(gateway_port if gateway_port is not None else RPC_PORT)
        self.is_running = False
        self.key_manager = NodeKeyManager(self.node_id)

        self.known_nodes = {}
        self.mempool = []
        self.mempool_lock = threading.Lock()

        # Ledger — each node has its own subfolder BLOCKCHAIN_DB/node_{port}/
        ledger_dir = Path(__file__).parent / "BLOCKCHAIN_DB" / f"node_{self.port}"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / "ledger.json"
        self.ledger_dir = ledger_dir
        self.ledger = Ledger(ledger_path=str(ledger_path))
        self.seen_tx_ids = set()
        for block in self.ledger.blocks:
            for tx in getattr(block, 'transactions', []):
                tx_data = getattr(tx, 'data', {}) if tx else {}
                tx_id = tx_data.get('tx_id')
                if tx_id:
                    self.seen_tx_ids.add(tx_id)

        # Last block on our chain
        self.last_block_index = self.ledger.get_last_block().index if self.ledger.blocks else -1
        self.last_block_hash = self.ledger.get_last_hash()

        self._gateway_handshake_logged = False

        # Mining control: event shared with miner process; when set, miner stops
        self.stop_mining_event = multiprocessing.Event()
        self.result_queue = multiprocessing.Queue()  # single queue for all miner runs
        self.miner_process = None
        self.mining_lock = threading.Lock()
        self._spinner_stop = threading.Event()
        self._spinner_thread = None

        self._register_node()
        # Seed peers from config so block broadcast reaches all nodes regardless of startup order
        for p in NODE_PORTS:
            if p != self.port:
                self.known_nodes[f"node_{p}"] = (RPC_HOST, p)
        logger.info("node started port=%s node_id=%s difficulty=%s", port, self.node_id[:8], difficulty)

    def _register_node(self):
        pass  # No DB

    def _register_with_gateway_once(self):
        """Length-prefixed JSON handshake so the gateway adds this node to its broadcast set."""
        try:
            peer_host = '127.0.0.1' if self.host in ('0.0.0.0', '') else self.host
            payload = json.dumps({
                'type': 'node_register',
                'node_id': self.node_id,
                'host': peer_host,
                'port': self.port,
            }).encode()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(DEFAULT_SOCKET_TIMEOUT)
            sock.connect((self.gateway_host, self.gateway_port))
            sock.send(struct.pack('>H', len(payload)) + payload)
            try:
                sock.recv(65536)
            except Exception:
                pass
            sock.close()
            if not self._gateway_handshake_logged:
                logger.info(
                    "gateway handshake ok -> %s:%s (this node %s:%s)",
                    self.gateway_host,
                    self.gateway_port,
                    peer_host,
                    self.port,
                )
                self._gateway_handshake_logged = True
            else:
                logger.debug(
                    "gateway heartbeat %s:%s node %s:%s",
                    self.gateway_host,
                    self.gateway_port,
                    peer_host,
                    self.port,
                )
        except Exception as e:
            logger.debug("gateway handshake failed: %s", e)

    def _start_gateway_heartbeat(self):
        """Re-register periodically so the gateway does not prune this node."""

        def loop():
            interval_s = max(15, NODE_REGISTRY_STALE_SECONDS // 3)
            while self.is_running:
                self._register_with_gateway_once()
                for _ in range(interval_s):
                    if not self.is_running:
                        return
                    time.sleep(1)

        threading.Thread(target=loop, daemon=True).start()

    def discover_nodes(self):
        """Discover peers from config; only add nodes whose port is in NODE_PORTS."""
        for p in NODE_PORTS:
            if p != self.port:
                self.known_nodes[f"node_{p}"] = (RPC_HOST, p)
        logger.info("discovered %s peers (ports in NODE_PORTS)", len(self.known_nodes))

    def _is_allowed_miner(self, public_key_pem):
        if not ENFORCE_MINER_ALLOWLIST:
            return True
        if not ALLOWED_MINER_KEY_FINGERPRINTS:
            return True
        if not public_key_pem:
            return False
        fp = _fingerprint_public_key(public_key_pem)
        return fp in ALLOWED_MINER_KEY_FINGERPRINTS

    def _is_timestamp_valid(self, ts_str):
        if not ts_str:
            return False
        try:
            ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            delta = abs((now - ts).total_seconds())
            return delta <= TX_TIME_WINDOW_SECONDS
        except Exception:
            return False

    def _validate_incoming_tx(self, sender, data, signature, public_key_b64):
        tx_id = data.get('tx_id') if isinstance(data, dict) else None
        timestamp = data.get('timestamp') if isinstance(data, dict) else None
        if not tx_id or not timestamp:
            return False, "missing tx_id/timestamp"
        if tx_id in self.seen_tx_ids:
            return False, "duplicate tx_id"
        if not self._is_timestamp_valid(timestamp):
            return False, "stale timestamp"
        if not public_key_b64 or not signature:
            return False, "missing signature"
        message_bytes = _canonical_tx_message(sender, data)
        if not _verify_ed25519_signature(public_key_b64, message_bytes, signature):
            return False, "invalid signature"
        return True, "ok"

    def start_listening(self):
        self.is_running = True
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(5)
        logger.info("listening on %s:%s", self.host, self.port)

        # Thread that checks result_queue when we are mining
        def result_collector():
            while self.is_running:
                try:
                    if self.result_queue.empty():
                        time.sleep(0.1)
                        continue
                    block_hash, nonce = self.result_queue.get_nowait()
                    self._on_block_mined(block_hash, nonce)
                except Exception:
                    time.sleep(0.1)

        threading.Thread(target=result_collector, daemon=True).start()

        while self.is_running:
            try:
                client_socket, (client_host, client_port) = server_socket.accept()
                threading.Thread(
                    target=self._handle_p2p_connection,
                    args=(client_socket, client_host, client_port),
                    daemon=True
                ).start()
            except Exception:
                if not self.is_running:
                    break
        server_socket.close()

    def _handle_p2p_connection(self, client_socket, client_host, client_port):
        try:
            data = client_socket.recv(4096)
            if not data:
                client_socket.close()
                return
            message = json.loads(data.decode())
            msg_type = message.get('type')

            if msg_type == 'ping':
                client_socket.send(json.dumps({'type': 'pong', 'node_id': self.node_id}).encode())
                client_socket.close()
            elif msg_type == 'node_discovery':
                client_socket.send(json.dumps({
                    'type': 'node_list',
                    'nodes': [{'node_id': nid, 'host': h, 'port': p} for nid, (h, p) in self.known_nodes.items()]
                }).encode())
                client_socket.close()
            elif msg_type == 'new_block':
                self._handle_new_block(message)
                client_socket.close()
            elif msg_type == 'STOP_MINING':
                self._stop_mining("stop_mining")
                client_socket.close()
            elif msg_type == 'NEW_TRANSACTION':
                self._handle_new_transaction(message, client_socket)
            else:
                client_socket.close()
        except Exception as e:
            try:
                client_socket.close()
            except Exception:
                pass

    def _handle_new_block(self, message):
        """Validate block (PoW + signature + prev_hash), write to DB, stop our miner."""
        payload = message.get('data', {})
        block_index = payload.get('index')
        timestamp = payload.get('timestamp')
        prev_hash = payload.get('prev_hash')
        current_hash = payload.get('current_hash')
        nonce = payload.get('nonce')
        miner_id = payload.get('miner_id')
        signature = payload.get('signature')
        public_key_pem = payload.get('public_key_pem')
        tx_list = payload.get('transactions', [])

        if block_index is None or current_hash is None or nonce is None or miner_id is None or signature is None:
            logger.warning("validation failed: missing fields")
            return
        if not public_key_pem:
            logger.warning("validation failed: missing public_key_pem")
            return

        # 1) PoW: hash starts with N zeros
        if not current_hash.startswith('0' * self.difficulty):
            logger.warning("validation failed: PoW %s...", current_hash[:16])
            return
        logger.info("validation: PoW ok block_index=%s", block_index)

        # 2) Signature: verify block hash signed by miner
        try:
            if not NodeKeyManager.verify_signature(public_key_pem, current_hash, signature):
                logger.warning("validation failed: signature")
                return
        except Exception as e:
            logger.warning("validation failed: signature error %s", e)
            return
        logger.info("validation: signature ok")

        if not self._is_allowed_miner(public_key_pem):
            logger.warning("validation failed: miner not allowlisted")
            return

        # 3) Chain: prev_hash must match our latest block
        if block_index != self.last_block_index + 1:
            logger.warning("validation failed: index %s expected %s", block_index, self.last_block_index + 1)
            return
        if prev_hash != self.last_block_hash:
            logger.warning("validation failed: prev_hash mismatch")
            return
        logger.info("validation: chain ok prev_hash link")

        # Validate transactions
        for tx in tx_list:
            sender = tx.get('sender', '')
            data = tx.get('data', {})
            sig = tx.get('signature', '')
            pub = tx.get('public_key', '')
            ok, reason = self._validate_incoming_tx(sender, data, sig, pub)
            if not ok:
                logger.warning("validation failed: tx rejected (%s)", reason)
                return

        # Write to our ledger
        try:
            transactions = [Transaction.from_dict(tx) for tx in tx_list]
            block = Block(
                index=block_index,
                timestamp=timestamp,
                prev_hash=prev_hash,
                current_hash=current_hash,
                nonce=nonce,
                miner_id=miner_id,
                signature=signature,
                public_key_pem=public_key_pem,
                transactions=transactions
            )
            self.ledger.add_block(block)
        except Exception as e:
            logger.error("Ledger write failed: %s", e)
            return

        for tx in tx_list:
            tx_id = tx.get('data', {}).get('tx_id') if isinstance(tx, dict) else None
            if tx_id:
                self.seen_tx_ids.add(tx_id)

        self.last_block_index = block_index
        self.last_block_hash = current_hash
        logger.info("gossip: block accepted index=%s hash=%s...", block_index, current_hash[:16])

        # Stop our miner so we don't keep hashing
        self._stop_mining("new_block")

    def _handle_new_transaction(self, message, client_socket):
        try:
            tx_data = message.get('data', {})
            sender = message.get('sender', '')
            signature = message.get('signature', '')
            public_key = message.get('public_key', '')
            start_timestamp = datetime.utcnow().isoformat()

            ack = {'type': 'MINING_STARTED', 'miner': self.node_id, 'message': 'Mining started'}
            client_socket.send(json.dumps(ack).encode())
            client_socket.close()

            ok, reason = self._validate_incoming_tx(sender, tx_data, signature, public_key)
            if not ok:
                logger.warning("tx rejected: %s", reason)
                return

            with self.mempool_lock:
                tx_id = tx_data.get('tx_id')
                if tx_id in self.seen_tx_ids:
                    logger.warning("tx rejected: duplicate tx_id")
                    return
                self.mempool.append({
                    'sender': sender,
                    'data': tx_data,
                    'signature': signature,
                    'public_key': public_key,
                    'start_timestamp': start_timestamp,
                })

            logger.info("gossip: NEW_TRANSACTION received sender=%s", sender)
            self._start_mining_if_needed()
        except Exception as e:
            try:
                client_socket.send(json.dumps({'type': 'ERROR', 'error': str(e)}).encode())
            except Exception:
                pass
            try:
                client_socket.close()
            except Exception:
                pass

    def _start_mining_if_needed(self):
        """Start miner process if not already mining. Uses first tx in mempool."""
        with self.mining_lock:
            if self.miner_process is not None and self.miner_process.is_alive():
                return
        with self.mempool_lock:
            if not self.mempool:
                return
            tx = self.mempool[0]

        self.stop_mining_event.clear()
        # Data to hash: prev_hash + timestamp + tx payload (deterministic)
        ts = datetime.utcnow().isoformat()
        data_to_hash = json.dumps({
            'prev_hash': self.last_block_hash,
            'timestamp': ts,
            'index': self.last_block_index + 1,
            'tx': tx
        }, sort_keys=True)

        self.miner_process = multiprocessing.Process(
            target=hashing_process,
            args=(data_to_hash, self.difficulty, self.stop_mining_event, self.result_queue)
        )
        self.miner_process.start()
        self._start_spinner()
        logger.info("hashing: mining started difficulty=%s", self.difficulty)

    def _stop_mining(self, reason):
        """Stop miner process and clear stop event."""
        self.stop_mining_event.set()
        self._stop_spinner()
        if self.miner_process and self.miner_process.is_alive():
            self.miner_process.join(timeout=2)
            if self.miner_process.is_alive():
                self.miner_process.terminate()
        logger.info("mining stopped reason=%s", reason)

    def _on_block_mined(self, block_hash, nonce):
        """We found a block: sign, write to ledger, broadcast, clear mempool for that tx."""
        self._stop_spinner()
        with self.mempool_lock:
            if not self.mempool:
                return
            tx = self.mempool.pop(0)

        block_index = self.last_block_index + 1
        prev_hash = self.last_block_hash
        timestamp = datetime.utcnow().isoformat()
        signature = self.key_manager.sign_data(block_hash)
        public_key_pem = self.key_manager.get_public_key_pem()

        try:
            transaction = Transaction(
                sender=tx.get('sender', ''),
                data=tx.get('data', {}),
                signature=tx.get('signature', ''),
                public_key=tx.get('public_key', ''),
                start_timestamp=tx.get('start_timestamp'),
                end_timestamp=timestamp
            )
            block = Block(
                index=block_index,
                timestamp=timestamp,
                prev_hash=prev_hash,
                current_hash=block_hash,
                nonce=nonce,
                miner_id=self.node_id,
                signature=signature,
                public_key_pem=public_key_pem,
                transactions=[transaction]
            )
            self.ledger.add_block(block)
        except Exception as e:
            logger.error("Ledger write failed: %s", e)
            return

        self.last_block_index = block_index
        self.last_block_hash = block_hash
        logger.info("block mined index=%s hash=%s...", block_index, block_hash[:16])
        tx_id = tx.get('data', {}).get('tx_id') if isinstance(tx, dict) else None
        if tx_id:
            self.seen_tx_ids.add(tx_id)

        payload = {
            'index': block_index,
            'timestamp': timestamp,
            'prev_hash': prev_hash,
            'current_hash': block_hash,
            'nonce': nonce,
            'miner_id': self.node_id,
            'signature': signature,
            'public_key_pem': public_key_pem,
            'transactions': [tx]
        }
        self._broadcast_block(payload)
        self._send_block_confirmation(block_index, block_hash, timestamp, [tx])

        # Start mining next tx if any
        with self.mempool_lock:
            if self.mempool:
                self._start_mining_if_needed()

    def _broadcast_block(self, payload):
        """Broadcast new_block to all known nodes."""
        message = {'type': 'new_block', 'node_id': self.node_id, 'data': payload}
        raw = json.dumps(message).encode()
        for node_id, (host, port) in list(self.known_nodes.items()):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                sock.send(raw)
                sock.close()
            except Exception:
                pass
        logger.info("gossip: block broadcast to %s peers", len(self.known_nodes))

    def _send_block_confirmation(self, block_index, block_hash, timestamp, transactions=None):
        """Notify RPC server so it can forward to main server (with tx list for wallet updates)."""
        try:
            msg = {
                'type': 'block_confirmation',
                'block_index': block_index,
                'block_hash': block_hash,
                'miner_id': self.node_id,
                'node_id': self.node_id,
                'timestamp': timestamp,
                'transactions': transactions or [],
            }
            raw = json.dumps(msg).encode()
            length = struct.pack('>H', len(raw))
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((self.gateway_host, self.gateway_port))
            sock.send(length + raw)
            sock.close()
            logger.info("block_confirmation sent to RPC block_index=%s", block_index)
        except Exception as e:
            logger.warning("send block_confirmation to RPC failed: %s", e)

    def stop(self):
        self.is_running = False
        self._stop_mining("shutdown")
        logger.info("node stopping")

    def _spinner_loop(self):
        symbols = ['\\', '|', '/', '-']
        idx = 0
        try:
            sys.stdout.write("Processing... ")
            sys.stdout.flush()
            while not self._spinner_stop.is_set():
                sys.stdout.write(f"\rProcessing... {symbols[idx % len(symbols)]}")
                sys.stdout.flush()
                time.sleep(0.1)
                idx += 1
        except Exception:
            return
        finally:
            sys.stdout.write("\rProcessing... done\n")
            sys.stdout.flush()

    def _start_spinner(self):
        if self._spinner_thread and self._spinner_thread.is_alive():
            return
        self._spinner_stop.clear()
        self._spinner_thread = threading.Thread(target=self._spinner_loop, daemon=True)
        self._spinner_thread.start()

    def _stop_spinner(self):
        self._spinner_stop.set()
