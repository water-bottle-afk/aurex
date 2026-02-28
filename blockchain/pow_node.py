"""
PoW Node - Proof of Work blockchain node with P2P gossip and multiprocessing miner.
- Main thread/listener: P2P, mempool, block validation, SQLite writes.
- Mining process: dedicated SHA-256 hashing loop; stopped by multiprocessing.Event when peer wins.
"""

import socket
import json
import hashlib
import time
import uuid
import threading
import multiprocessing
import logging
import struct
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from key_manager import NodeKeyManager
from db_init import (
    get_db_connection,
    get_node_db_path,
    init_node_database,
    get_node_db_connection,
)
from config import NODE_PORTS, RPC_HOST, RPC_PORT

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('pow_node')


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
    Each node has its own ledger: blockchain/node_{port}.sqlite3.
    """

    def __init__(self, host='0.0.0.0', port=11111, difficulty=2):
        self.node_id = str(uuid.uuid4())
        self.host = host
        self.port = port
        self.difficulty = difficulty
        self.is_running = False
        self.key_manager = NodeKeyManager(self.node_id)

        self.known_nodes = {}
        self.mempool = []
        self.mempool_lock = threading.Lock()

        # Last block on our chain (from our DB)
        self.last_block_index = -1
        self.last_block_hash = '0' * 64

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
        init_node_database(port)
        self._load_last_block()
        logger.info("node started port=%s node_id=%s difficulty=%s", port, self.node_id[:8], difficulty)

    def _load_last_block(self):
        """Load last block from this node's DB to set last_block_index/hash."""
        try:
            conn = get_node_db_connection(self.port)
            cursor = conn.cursor()
            cursor.execute(
                'SELECT "index", current_hash FROM blocks ORDER BY "index" DESC LIMIT 1'
            )
            row = cursor.fetchone()
            conn.close()
            if row:
                self.last_block_index = row[0]
                self.last_block_hash = row[1]
                logger.info("last block loaded index=%s hash=%s...", self.last_block_index, self.last_block_hash[:16])
        except Exception as e:
            logger.warning("could not load last block: %s", e)

    def _register_node(self):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT OR REPLACE INTO nodes (node_id, host, port, node_type, status) VALUES (?, ?, ?, ?, ?)',
                (self.node_id, self.host, self.port, 'full-node', 'active')
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning("could not register node: %s", e)

    def discover_nodes(self):
        """Discover peers from DB; only add nodes whose port is in NODE_PORTS (ignore stale rows)."""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                'SELECT node_id, host, port FROM nodes WHERE status = ? AND node_id != ?',
                ('active', self.node_id)
            )
            added = 0
            for row in cursor.fetchall():
                nid, h, p = row[0], row[1], row[2]
                if p in NODE_PORTS and p != self.port:
                    self.known_nodes[nid] = (h, p)
                    added += 1
            conn.close()
            logger.info("discovered %s peers (ports in NODE_PORTS)", len(self.known_nodes))
        except Exception as e:
            logger.warning("discover nodes: %s", e)

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

        # 3) Chain: prev_hash must match our latest block
        if block_index != self.last_block_index + 1:
            logger.warning("validation failed: index %s expected %s", block_index, self.last_block_index + 1)
            return
        if prev_hash != self.last_block_hash:
            logger.warning("validation failed: prev_hash mismatch")
            return
        logger.info("validation: chain ok prev_hash link")

        # Write to our ledger (same thread as listener = safe for SQLite)
        try:
            conn = get_node_db_connection(self.port)
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO blocks ("index", timestamp, prev_hash, current_hash, nonce, miner_id, signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (block_index, timestamp, prev_hash, current_hash, nonce, miner_id, signature)
            )
            end_ts = timestamp
            for tx in tx_list:
                sender = tx.get('sender', '')
                data_str = json.dumps(tx.get('data', tx)) if isinstance(tx.get('data'), dict) else str(tx.get('data', ''))
                sig = tx.get('signature', '')
                start_ts = tx.get('start_timestamp') or end_ts
                cursor.execute(
                    'INSERT INTO transactions (block_hash, sender, data, signature, start_timestamp, end_timestamp) VALUES (?, ?, ?, ?, ?, ?)',
                    (current_hash, sender, data_str, sig, start_ts, end_ts)
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error("DB write failed: %s", e)
            return

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
            start_timestamp = datetime.utcnow().isoformat()

            ack = {'type': 'MINING_STARTED', 'miner': self.node_id, 'message': 'Mining started'}
            client_socket.send(json.dumps(ack).encode())
            client_socket.close()

            with self.mempool_lock:
                self.mempool.append({
                    'sender': sender, 'data': tx_data, 'signature': signature,
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
        """We found a block: sign, write to DB, broadcast, clear mempool for that tx."""
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

        end_timestamp = timestamp
        start_timestamp = tx.get('start_timestamp') or end_timestamp
        try:
            conn = get_node_db_connection(self.port)
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO blocks ("index", timestamp, prev_hash, current_hash, nonce, miner_id, signature)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (block_index, timestamp, prev_hash, block_hash, nonce, self.node_id, signature)
            )
            data_str = json.dumps(tx['data']) if isinstance(tx['data'], dict) else str(tx['data'])
            cursor.execute(
                'INSERT INTO transactions (block_hash, sender, data, signature, start_timestamp, end_timestamp) VALUES (?, ?, ?, ?, ?, ?)',
                (block_hash, tx.get('sender', ''), data_str, tx.get('signature', ''), start_timestamp, end_timestamp)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error("DB write failed: %s", e)
            return

        self.last_block_index = block_index
        self.last_block_hash = block_hash
        logger.info("block mined index=%s hash=%s...", block_index, block_hash[:16])

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
            sock.connect((RPC_HOST, RPC_PORT))
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
