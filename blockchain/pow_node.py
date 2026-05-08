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
import sqlite3
from datetime import datetime, timezone
import sys
import os
import base64
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ed25519

sys.path.insert(0, os.path.dirname(__file__))

from key_manager import NodeKeyManager
from classes import Ledger, Block, Transaction, StateManager
from config import (
    NODE_PORTS,
    RPC_HOST,
    RPC_PORT,
    DEFAULT_SOCKET_TIMEOUT,
    TX_TIME_WINDOW_SECONDS,
    ENFORCE_MINER_ALLOWLIST,
    ALLOWED_MINER_KEY_FINGERPRINTS,
    NODE_REGISTRY_STALE_SECONDS,
    MAX_NEIGHBORS,
)
from protocol import Protocol

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


def hashing_process(data_hash, difficulty, stop_event, result_queue):
    """
    CPU-bound mining loop. Runs in a separate process.
    data_hash is a pre-computed SHA-256 hex digest of the block header —
    only a fixed 64-char string is concatenated per iteration.
    Exits when stop_event is set (peer found block) or when nonce is found.
    """
    nonce = 0
    target = '0' * int(difficulty)
    try:
        while not stop_event.is_set():
            hash_attempt = hashlib.sha256(f"{data_hash}{nonce}".encode()).hexdigest()
            try:
                if not hash_attempt.startswith(target):
                    sys.stdout.write(".")
                    sys.stdout.flush()
                else:
                    sys.stdout.write(f"\n[nonce={nonce}] {hash_attempt[:16]}...\n")
                    sys.stdout.flush()
            except (BrokenPipeError, OSError, ValueError):
                stop_event.set()
                return
            if hash_attempt.startswith(target):
                result_queue.put((hash_attempt, nonce))
                return
            nonce += 1
    except Exception:
        stop_event.set()
        return


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
        self.marketplace_db_path = Path(__file__).parent.parent / "DB" / "marketplace.db"
        self.state_manager = StateManager()
        self.committed_tx_ids = set()
        self.mempool_tx_ids = set()

        # Ledger — each node has its own subfolder BLOCKCHAIN_DB/node_{port}/
        ledger_dir = Path(__file__).parent / "BLOCKCHAIN_DB" / f"node_{self.port}"
        ledger_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = ledger_dir / "ledger.json"
        self.ledger_dir = ledger_dir
        self.ledger = Ledger(ledger_path=str(ledger_path))
        if not ledger_path.exists():
            self.ledger.save()
        logger.info("ledger ready path=%s blocks=%s", ledger_path, len(self.ledger.blocks))
        self.seen_block_hashes = set()
        self.inflight_tx_ids = set()
        for block in self.ledger.blocks:
            if getattr(block, 'current_hash', None):
                self.seen_block_hashes.add(block.current_hash)
        self._seed_balances_from_db()
        self._rebuild_state_from_ledger()

        # Last block on our chain
        self.last_block_index = self.ledger.get_last_block().index if self.ledger.blocks else -1
        self.last_block_hash = self.ledger.get_last_hash()

        self._gateway_handshake_logged = False

        # Mining control: event shared with miner process; when set, miner stops
        self.stop_mining_event = multiprocessing.Event()
        self.result_queue = multiprocessing.Queue()  # single queue for all miner runs
        self.miner_process = None
        self.mining_lock = threading.Lock()
        self._register_node()
        self._select_neighbors()
        logger.info("node started port=%s node_id=%s difficulty=%s neighbors=%s",
                    port, self.node_id[:8], difficulty, list(self.known_nodes.keys()))

    def _register_node(self):
        pass  # No DB

    def _register_with_gateway_once(self):
        """Length-prefixed JSON handshake so the gateway adds this node to its broadcast set."""
        try:
            peer_host = '127.0.0.1' if self.host in ('0.0.0.0', '') else self.host
            payload = {
                'type': 'node_register',
                'node_id': self.node_id,
                'host': peer_host,
                'port': self.port,
            }
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(DEFAULT_SOCKET_TIMEOUT)
            sock.connect((self.gateway_host, self.gateway_port))
            Protocol.send_lp_json(sock, payload)
            Protocol.recv_lp_json(sock)
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
        """Discover peers from config; keep a bounded neighbor set."""
        self._select_neighbors()
        logger.info("discovered %s peers (neighbors=%s)", len(self.known_nodes), list(self.known_nodes.keys()))

    def _select_neighbors(self):
        """Select a bounded neighbor set to avoid full mesh."""
        ports = list(NODE_PORTS)
        if self.port not in ports:
            return
        if len(ports) <= 1:
            return
        idx = ports.index(self.port)
        desired = min(MAX_NEIGHBORS, len(ports) - 1)
        neighbors = []
        step = 1
        while len(neighbors) < desired and step < len(ports):
            right = ports[(idx + step) % len(ports)]
            left = ports[(idx - step) % len(ports)]
            for p in (right, left):
                if p != self.port and p not in neighbors:
                    neighbors.append(p)
                    if len(neighbors) >= desired:
                        break
            step += 1
        self.known_nodes = {f"node_{p}": (RPC_HOST, p) for p in neighbors}

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

    def _is_ed25519_public_key_b64(self, value):
        if not value or not isinstance(value, str):
            return False
        try:
            raw = base64.b64decode(value.encode())
            return len(raw) == 32
        except Exception:
            return False

    def _lookup_public_key_by_username(self, username):
        if not username:
            return ''
        conn = None
        try:
            conn = sqlite3.connect(str(self.marketplace_db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                cur.execute('SELECT wallet_public_key FROM users WHERE username = ? LIMIT 1', (username,))
                row = cur.fetchone()
                if row and row['wallet_public_key']:
                    return str(row['wallet_public_key'])
            except Exception:
                pass
            try:
                cur.execute('SELECT public_key_hex FROM wallets WHERE username = ? LIMIT 1', (username,))
                row = cur.fetchone()
                if row and row['public_key_hex']:
                    return str(row['public_key_hex'])
            except Exception:
                pass
            return ''
        except Exception:
            return ''
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass

    def _resolve_identity_public_key(self, identity, fallback_public_key=''):
        if identity and self._is_ed25519_public_key_b64(identity):
            return identity
        if identity:
            resolved = self._lookup_public_key_by_username(str(identity))
            if resolved and self._is_ed25519_public_key_b64(resolved):
                return resolved
        if fallback_public_key and self._is_ed25519_public_key_b64(fallback_public_key):
            return fallback_public_key
        return ''

    def _seed_balances_from_db(self):
        """Seed balances from SQL once; chain replay applies deterministic deltas on top."""
        conn = None
        try:
            conn = sqlite3.connect(str(self.marketplace_db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            rows = []
            try:
                cur.execute(
                    '''
                    SELECT username, wallet_public_key, wallet_balance
                    FROM users
                    WHERE wallet_public_key IS NOT NULL AND wallet_public_key != ''
                    '''
                )
                rows.extend(cur.fetchall() or [])
            except Exception:
                pass
            try:
                cur.execute(
                    '''
                    SELECT w.username, w.public_key_hex AS wallet_public_key, u.wallet_balance
                    FROM wallets w
                    LEFT JOIN users u ON u.username = w.username
                    WHERE w.public_key_hex IS NOT NULL AND w.public_key_hex != ''
                    '''
                )
                rows.extend(cur.fetchall() or [])
            except Exception:
                pass

            for row in rows:
                pk = row['wallet_public_key'] if isinstance(row, sqlite3.Row) else None
                if not pk or not self._is_ed25519_public_key_b64(pk):
                    continue
                bal = row['wallet_balance'] if isinstance(row, sqlite3.Row) else None
                try:
                    bal_int = StateManager.amount_to_int(StateManager.INITIAL_COINS if bal is None else bal)
                except Exception:
                    try:
                        base = StateManager.INITIAL_COINS if bal is None else bal
                        bal_int = int(float(base) * 100)
                    except Exception:
                        bal_int = StateManager.INITIAL_BALANCE_INT
                self.state_manager.set_balance(pk, bal_int)
        except Exception as e:
            logger.warning("seed balances from DB failed: %s", e)
        finally:
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass

    def _normalize_tx_type(self, data):
        if not isinstance(data, dict):
            return ''
        raw = str(data.get('type') or data.get('action') or '').strip().upper()
        if raw in ('MINT', 'ASSET_MINT', 'UPLOAD'):
            return 'MINT'
        if raw in ('TRADE', 'BUY', 'ASSET_PURCHASE', 'PURCHASE'):
            return 'TRADE'
        return raw

    def _normalize_state_tx(self, sender, data, public_key_b64, state_snapshot):
        if not isinstance(data, dict):
            return None, "tx data must be object"
        tx_type = self._normalize_tx_type(data)
        image_hash = data.get('image_hash') or data.get('asset_hash')

        if tx_type == 'MINT':
            owner_hint = data.get('initial_owner') or data.get('owner_pub') or data.get('owner') or sender
            owner_pk = self._resolve_identity_public_key(owner_hint, fallback_public_key=public_key_b64)
            if not owner_pk:
                return None, "mint owner public key not resolved"
            return {
                'type': 'MINT',
                'image_hash': image_hash,
                'owner': owner_pk,
            }, "ok"

        if tx_type == 'TRADE':
            buyer_hint = data.get('buyer') or data.get('buyer_pub') or data.get('from') or sender
            seller_hint = data.get('seller') or data.get('seller_pub') or data.get('to')
            buyer_pk = self._resolve_identity_public_key(buyer_hint, fallback_public_key=public_key_b64)
            seller_pk = self._resolve_identity_public_key(seller_hint)
            if not seller_pk and image_hash:
                seller_pk = state_snapshot.ownership.get(image_hash, '')
            if not buyer_pk:
                return None, "trade buyer public key not resolved"
            if not seller_pk:
                return None, "trade seller public key not resolved"
            amount_raw = data.get('price') if data.get('price') is not None else data.get('amount')
            try:
                price_int = StateManager.amount_to_int(amount_raw)
            except Exception:
                return None, "trade invalid price"
            return {
                'type': 'TRADE',
                'image_hash': image_hash,
                'buyer': buyer_pk,
                'seller': seller_pk,
                'price_int': price_int,
            }, "ok"

        return None, f"unsupported tx type '{tx_type}'"

    def _validate_state_tx(self, state_tx, state_snapshot):
        tx_type = state_tx.get('type')
        if tx_type == 'MINT':
            return state_snapshot.validate_mint(state_tx.get('image_hash'), state_tx.get('owner'))
        if tx_type == 'TRADE':
            return state_snapshot.validate_trade(
                state_tx.get('image_hash'),
                state_tx.get('buyer'),
                state_tx.get('seller'),
                state_tx.get('price_int'),
            )
        return False, "unsupported state tx"

    def _apply_state_tx(self, state_tx, state_snapshot):
        tx_type = state_tx.get('type')
        if tx_type == 'MINT':
            return state_snapshot.apply_mint(state_tx.get('image_hash'), state_tx.get('owner'))
        if tx_type == 'TRADE':
            return state_snapshot.apply_trade(
                state_tx.get('image_hash'),
                state_tx.get('buyer'),
                state_tx.get('seller'),
                state_tx.get('price_int'),
            )
        return False, "unsupported state tx"

    def _extract_tx_fields(self, tx):
        if isinstance(tx, Transaction):
            return tx.sender, tx.data or {}, tx.signature or '', tx.public_key or ''
        if isinstance(tx, dict):
            return tx.get('sender', ''), tx.get('data', {}) or {}, tx.get('signature', ''), tx.get('public_key', '')
        return '', {}, '', ''

    def _build_state_with_mempool(self):
        staged = self.state_manager.copy()
        with self.mempool_lock:
            pending = list(self.mempool)
        for tx in pending:
            sender, data, _sig, public_key = self._extract_tx_fields(tx)
            state_tx, _ = self._normalize_state_tx(sender, data, public_key, staged)
            if not state_tx:
                continue
            self._apply_state_tx(state_tx, staged)
        return staged

    def _validate_incoming_tx(
        self,
        sender,
        data,
        signature,
        public_key_b64,
        *,
        state_snapshot=None,
        enforce_timestamp=True,
        check_duplicate_cache=True,
    ):
        tx_id = data.get('tx_id') if isinstance(data, dict) else None
        timestamp = data.get('timestamp') if isinstance(data, dict) else None
        if tx_id:
            logger.info("tx validate start tx_id=%s sender=%s", tx_id, sender)
        if not tx_id or not timestamp:
            return False, "missing tx_id/timestamp"
        if check_duplicate_cache and tx_id in self.committed_tx_ids:
            return False, "duplicate tx_id"
        if enforce_timestamp and not self._is_timestamp_valid(timestamp):
            return False, "stale timestamp"
        if not public_key_b64 or not signature:
            return False, "missing signature"
        message_bytes = _canonical_tx_message(sender, data)
        if not _verify_ed25519_signature(public_key_b64, message_bytes, signature):
            return False, "invalid signature"

        state_snapshot = state_snapshot or self.state_manager
        state_tx, reason = self._normalize_state_tx(sender, data, public_key_b64, state_snapshot)
        if not state_tx:
            return False, reason
        ok, reason = self._validate_state_tx(state_tx, state_snapshot)
        if not ok:
            return False, reason
        if tx_id:
            logger.info("tx validate ok tx_id=%s", tx_id)
        return True, "ok"

    def apply_block(self, block):
        """
        Validate and apply every transaction in a block atomically.
        State updates only commit after the full block passes.
        """
        staged_state = self.state_manager.copy()
        staged_tx_ids = set(self.committed_tx_ids)
        txs = list(getattr(block, 'transactions', []) or [])

        for tx in txs:
            sender, data, signature, public_key = self._extract_tx_fields(tx)
            tx_id = data.get('tx_id') if isinstance(data, dict) else None
            if tx_id and tx_id in staged_tx_ids:
                return False, f"duplicate tx_id in chain ({tx_id})"
            ok, reason = self._validate_incoming_tx(
                sender,
                data,
                signature,
                public_key,
                state_snapshot=staged_state,
                enforce_timestamp=False,
                check_duplicate_cache=False,
            )
            if not ok:
                return False, reason

            state_tx, reason = self._normalize_state_tx(sender, data, public_key, staged_state)
            if not state_tx:
                return False, reason
            ok, reason = self._apply_state_tx(state_tx, staged_state)
            if not ok:
                return False, reason
            if tx_id:
                staged_tx_ids.add(tx_id)

        self.state_manager = staged_state
        self.committed_tx_ids = staged_tx_ids
        return True, "ok"

    def _rebuild_state_from_ledger(self):
        seed_balances = dict(self.state_manager.balances)
        self.state_manager = StateManager(balances=seed_balances)
        self.committed_tx_ids = set()
        for block in self.ledger.blocks:
            ok, reason = self.apply_block(block)
            if not ok:
                logger.warning("ledger replay halted at block=%s: %s", getattr(block, 'index', '?'), reason)
                break

    def start_listening(self):
        self.is_running = True
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(5)
        logger.info("listening on %s:%s", self.host, self.port)
        # Register with gateway and keep heartbeating so gateway uses live peers.
        self._register_with_gateway_once()
        self._start_gateway_heartbeat()

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
                self._stop_mining("peer_disconnect")
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
            self._stop_mining("peer_error")
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
        sender_node = message.get('node_id') or message.get('relay')
        if current_hash and current_hash in self.seen_block_hashes:
            logger.info("gossip: block already seen hash=%s...", current_hash[:16])
            return

        if block_index is None or current_hash is None or nonce is None or miner_id is None or signature is None:
            logger.warning("validation failed: missing fields")
            return
        if not public_key_pem:
            logger.warning("validation failed: missing public_key_pem")
            return
        logger.info("block validate start index=%s hash=%s...", block_index, str(current_hash)[:16])

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

        # Validate/apply transactions atomically against node state.
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
            transactions=transactions,
        )
        ok, reason = self.apply_block(block)
        if not ok:
            logger.warning("validation failed: block tx/state rejected (%s)", reason)
            return

        try:
            self.ledger.add_block(block)
            logger.info("ledger saved block_index=%s txs=%s", block_index, len(transactions))
        except Exception as e:
            logger.error("Ledger write failed: %s", e)
            return

        self.last_block_index = block_index
        self.last_block_hash = current_hash
        if current_hash:
            self.seen_block_hashes.add(current_hash)
        logger.info("gossip: block accepted index=%s hash=%s...", block_index, current_hash[:16])

        # Stop mining and drop any matching mempool/inflight txs
        tx_ids = set()
        for tx in tx_list:
            tx_id = tx.get('data', {}).get('tx_id') if isinstance(tx, dict) else None
            if tx_id:
                tx_ids.add(tx_id)
        if tx_ids:
            with self.mempool_lock:
                self.mempool = [t for t in self.mempool if (t.get('data', {}).get('tx_id') not in tx_ids)]
                for tx_id in list(tx_ids):
                    self.mempool_tx_ids.discard(tx_id)
                    if tx_id in self.inflight_tx_ids:
                        self.inflight_tx_ids.remove(tx_id)

        # Stop our miner so we don't keep hashing
        self._stop_mining("new_block")
        # Gossip onward to neighbors (exclude sender)
        self._broadcast_block(payload, relay_from=sender_node)
        # Count this node's validation as a confirmation in the gateway.
        self._send_block_confirmation(block_index, current_hash, timestamp, tx_list, miner_id=miner_id)
        logger.info("block validate done index=%s", block_index)

    def _handle_new_transaction(self, message, client_socket):
        inflight_added = False
        tx_id = None
        try:
            tx_data = message.get('data', {})
            sender = message.get('sender', '')
            signature = message.get('signature', '')
            public_key = message.get('public_key', '')
            tx_id = tx_data.get('tx_id') if isinstance(tx_data, dict) else None
            
            # Early duplicate check to prevent double processing
            if tx_id:
                with self.mempool_lock:
                    if tx_id in self.committed_tx_ids or tx_id in self.inflight_tx_ids or tx_id in self.mempool_tx_ids:
                        logger.warning("tx rejected: duplicate tx_id (%s)", tx_id)
                        client_socket.close()
                        return
                    self.inflight_tx_ids.add(tx_id)
                    inflight_added = True
            
            start_timestamp = datetime.now(timezone.utc).isoformat()
            tx_type = self._normalize_tx_type(tx_data) if isinstance(tx_data, dict) else 'unknown'
            relay = message.get('relay') or message.get('node_id') or ''
            if tx_type == 'MINT' and isinstance(tx_data, dict):
                file_name = tx_data.get('file_name') or tx_data.get('metadata_link') or ''
                if file_name:
                    logger.info("mint file received: %s", file_name)

            ack = {'type': 'MINING_STARTED', 'miner': self.node_id, 'message': 'Mining started'}
            client_socket.send(json.dumps(ack).encode())
            client_socket.close()

            state_for_validation = self._build_state_with_mempool()
            ok, reason = self._validate_incoming_tx(
                sender,
                tx_data,
                signature,
                public_key,
                state_snapshot=state_for_validation,
                enforce_timestamp=True,
                check_duplicate_cache=True,
            )
            if not ok:
                logger.warning("tx rejected (%s): %s", tx_type, reason)
                return

            with self.mempool_lock:
                self.mempool.append({
                    'sender': sender,
                    'data': tx_data,
                    'signature': signature,
                    'public_key': public_key,
                    'start_timestamp': start_timestamp,
                })
                if tx_id:
                    self.mempool_tx_ids.add(tx_id)
                    if tx_id in self.inflight_tx_ids:
                        self.inflight_tx_ids.remove(tx_id)

            logger.info("NEW_TRANSACTION queued: type=%s sender=%s tx_id=%s", tx_type, sender, tx_id)
            self._gossip_transaction(sender, tx_data, signature, public_key, relay_from=relay)
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
        finally:
            if inflight_added and tx_id:
                with self.mempool_lock:
                    if tx_id in self.inflight_tx_ids:
                        self.inflight_tx_ids.remove(tx_id)

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
        # Build a compact block header and pre-hash it once.
        # Only the 64-char hex digest is sent to the mining process,
        # so each loop iteration concatenates a fixed-size string.
        ts = datetime.now(timezone.utc).isoformat()
        tx_data = tx.get('data', {})
        header = json.dumps({
            'prev_hash': self.last_block_hash,
            'timestamp': ts,
            'index': self.last_block_index + 1,
            'sender': tx.get('sender', ''),
            'tx_id': tx_data.get('tx_id', '') if isinstance(tx_data, dict) else '',
            'action': tx_data.get('action', '') if isinstance(tx_data, dict) else '',
        }, sort_keys=True)
        data_to_hash = hashlib.sha256(header.encode()).hexdigest()

        self.miner_process = multiprocessing.Process(
            target=hashing_process,
            args=(data_to_hash, self.difficulty, self.stop_mining_event, self.result_queue)
        )
        self.miner_process.daemon = True
        self.miner_process.start()
        tx_id = tx.get('data', {}).get('tx_id') if isinstance(tx, dict) else None
        logger.info("hashing: mining started difficulty=%s tx_id=%s", self.difficulty, tx_id)

    def _stop_mining(self, reason):
        """Stop miner process and clear stop event."""
        self.stop_mining_event.set()
        if self.miner_process and self.miner_process.is_alive():
            self.miner_process.join(timeout=2)
            if self.miner_process.is_alive():
                self.miner_process.terminate()
        logger.info("mining stopped reason=%s", reason)

    def _on_block_mined(self, block_hash, nonce):
        """We found a block: sign, write to ledger, broadcast, clear mempool for that tx."""
        with self.mempool_lock:
            if not self.mempool:
                return
            tx = self.mempool.pop(0)
            tx_id = tx.get('data', {}).get('tx_id') if isinstance(tx, dict) else None
            if tx_id:
                self.mempool_tx_ids.discard(tx_id)

        block_index = self.last_block_index + 1
        prev_hash = self.last_block_hash
        timestamp = datetime.now(timezone.utc).isoformat()
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
            ok, reason = self.apply_block(block)
            if not ok:
                logger.warning("local mined block rejected by state rules: %s", reason)
                return
            self.ledger.add_block(block)
            logger.info("ledger saved block_index=%s tx_id=%s", block_index, tx_id)
        except Exception as e:
            logger.error("Ledger write failed: %s", e)
            return

        self.last_block_index = block_index
        self.last_block_hash = block_hash
        if block_hash:
            self.seen_block_hashes.add(block_hash)
        tx_type = self._normalize_tx_type(tx.get('data', {})) if isinstance(tx, dict) else 'unknown'
        logger.info("block mined index=%s hash=%s... type=%s tx_id=%s", block_index, block_hash[:16], tx_type, tx_id)

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
        self._send_block_confirmation(block_index, block_hash, timestamp, [tx], miner_id=self.node_id)
        logger.info("block broadcast+confirm sent index=%s tx_id=%s", block_index, tx_id)

        # Start mining next tx if any
        with self.mempool_lock:
            if self.mempool:
                self._start_mining_if_needed()

    def _broadcast_block(self, payload, relay_from=None):
        """Broadcast new_block to neighbor nodes (bounded fanout)."""
        message = {'type': 'new_block', 'node_id': self.node_id, 'relay': self.node_id, 'data': payload}
        raw = json.dumps(message).encode()
        for node_id, (host, port) in list(self.known_nodes.items()):
            if relay_from and node_id == relay_from:
                continue
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                sock.send(raw)
                sock.close()
            except Exception:
                pass
        logger.info("gossip: block broadcast to %s peers", len(self.known_nodes))

    def _gossip_transaction(self, sender, tx_data, signature, public_key, relay_from=None):
        """Forward NEW_TRANSACTION to neighbors (dedup handled by tx_id)."""
        message = {
            'type': 'NEW_TRANSACTION',
            'sender': sender,
            'data': tx_data,
            'signature': signature,
            'public_key': public_key,
            'relay': self.node_id,
        }
        raw = json.dumps(message).encode()
        for node_id, (host, port) in list(self.known_nodes.items()):
            if relay_from and node_id == relay_from:
                continue
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3)
                sock.connect((host, port))
                sock.send(raw)
                sock.close()
            except Exception:
                pass

    def _send_block_confirmation(self, block_index, block_hash, timestamp, transactions=None, miner_id=None):
        """Notify RPC server so it can forward to main server (with tx list for wallet updates)."""
        try:
            msg = {
                'type': 'block_confirmation',
                'block_index': block_index,
                'block_hash': block_hash,
                'miner_id': miner_id or self.node_id,
                'node_id': self.node_id,
                'timestamp': timestamp,
                'transactions': transactions or [],
            }
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            sock.connect((self.gateway_host, self.gateway_port))
            Protocol.send_lp_json(sock, msg)
            sock.close()
            logger.info("block_confirmation sent to RPC block_index=%s", block_index)
        except Exception as e:
            logger.warning("send block_confirmation to RPC failed: %s", e)

    def stop(self):
        self.is_running = False
        self._stop_mining("shutdown")
        logger.info("node stopping")

