"""
Gateway Server - Socket-based entry point (no Flask).
- Listens for submit_transaction, /buy, and health on RPC_LISTEN_PORT.
- Receives block_confirmation from nodes and forwards to main server.
"""

import json
import socket
import sys
import os
import threading
import argparse
import logging
import hashlib
from datetime import datetime, timezone
from pathlib import Path
import base64
import time

sys.path.insert(0, os.path.dirname(__file__))

from config import (
    NODE_PORTS,
    RPC_HOST,
    RPC_LISTEN_HOST,
    RPC_LISTEN_PORT,
    SERVER_NOTIFY_HOST,
    SERVER_NOTIFY_PORT,
    DEFAULT_POW_DIFFICULTY,
    TX_TIME_WINDOW_SECONDS,
    CHAIN_CONFIRMATIONS_REQUIRED,
    NODE_REGISTRY_STALE_SECONDS,
    NODE_REGISTRY_REAP_INTERVAL_SECONDS,
)
from models import Transaction
from db_init import get_db_connection, init_database
from classes import StateManager
from cryptography.hazmat.primitives.asymmetric import ed25519
from protocol import Protocol

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('gateway_server')

SOCKET_TIMEOUT = 3
SEEN_TX_IDS = {}
SEEN_TX_LOCK = threading.Lock()
CONFIRMATION_LOCK = threading.Lock()
BLOCK_CONFIRMATIONS = {}  # (index, hash) -> {'nodes': set(), 'confirmation': dict}
COMMITTED_BY_INDEX = {}   # index -> hash
GATEWAY_STATE = StateManager()
STATE_LOCK = threading.Lock()

# (host, port) -> {'node_id': str, 'last_seen': monotonic time}
NODE_REGISTRY = {}
NODE_REGISTRY_LOCK = threading.Lock()
GUI_BRIDGE = None


def set_gui_bridge(bridge):
    global GUI_BRIDGE
    GUI_BRIDGE = bridge


def _emit_gui_event(node_id='', message='', event_type='system', direction='system', status='info', **extra):
    if GUI_BRIDGE is None:
        return
    try:
        GUI_BRIDGE.log_event(
            node_id=node_id or '',
            message=message,
            event_type=event_type,
            direction=direction,
            status=status,
            **extra,
        )
    except Exception:
        pass


def _normalize_peer_host(host):
    h = (host or RPC_HOST or '127.0.0.1').strip()
    if h in ('0.0.0.0', ''):
        return '127.0.0.1'
    return h


def register_peer(host, port, node_id=''):
    """Record or refresh a PoW node that registered / heartbeats with the gateway."""
    try:
        p = int(port)
    except (TypeError, ValueError):
        return False
    h = _normalize_peer_host(host)
    key = (h, p)
    nid = node_id or f'node_{p}'
    with NODE_REGISTRY_LOCK:
        NODE_REGISTRY[key] = {
            'node_id': nid,
            'last_seen': time.monotonic(),
        }
    logger.debug("node registry update %s:%s id=%s", h, p, nid)
    _emit_gui_event(
        node_id=nid,
        message=f"Node registered from {h}:{p}",
        event_type='node_status',
        direction='inbound',
        status='connected',
        address=f"{h}:{p}",
    )
    return True


def _prune_stale_peers():
    cutoff = time.monotonic() - NODE_REGISTRY_STALE_SECONDS
    with NODE_REGISTRY_LOCK:
        dead = [k for k, v in NODE_REGISTRY.items() if v.get('last_seen', 0) < cutoff]
        for k in dead:
            stale_info = NODE_REGISTRY.pop(k, None)
            if stale_info:
                _emit_gui_event(
                    node_id=stale_info.get('node_id', ''),
                    message=f"Node disconnected from {k[0]}:{k[1]}",
                    event_type='node_status',
                    direction='system',
                    status='disconnected',
                    address=f"{k[0]}:{k[1]}",
                )
        if dead:
            logger.info("node registry: pruned %s stale peer(s); active=%s", len(dead), len(NODE_REGISTRY))


def _registry_reaper_loop():
    while True:
        time.sleep(NODE_REGISTRY_REAP_INTERVAL_SECONDS)
        _prune_stale_peers()


def get_broadcast_targets():
    """
    Endpoints to send NEW_TRANSACTION / STOP_MINING to.
    Prefer dynamically registered nodes; if none are active, fall back to NODE_PORTS (bootstrap).
    """
    _prune_stale_peers()
    with NODE_REGISTRY_LOCK:
        endpoints = list(NODE_REGISTRY.keys())
    if endpoints:
        return endpoints, 'registry'
    return [(RPC_HOST, p) for p in NODE_PORTS], 'config_fallback'

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


def _is_timestamp_valid(ts_str):
    if not ts_str:
        return False
    try:
        ts = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=None)
        now = datetime.now(timezone.utc)
        delta = abs((now.replace(tzinfo=None) - ts.replace(tzinfo=None)).total_seconds())
        return delta <= TX_TIME_WINDOW_SECONDS
    except Exception:
        return False


def _register_tx_id(tx_id, ts_str):
    if not tx_id:
        return False, "missing tx_id"
    with SEEN_TX_LOCK:
        if tx_id in SEEN_TX_IDS:
            return False, "duplicate tx_id"
        SEEN_TX_IDS[tx_id] = ts_str or datetime.now(timezone.utc).isoformat()
    return True, "ok"


def _cleanup_seen_tx_ids():
    while True:
        time.sleep(max(30, TX_TIME_WINDOW_SECONDS))
        now = datetime.now(timezone.utc)
        with SEEN_TX_LOCK:
            to_delete = []
            for tx_id, ts_str in SEEN_TX_IDS.items():
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if abs((now.replace(tzinfo=None) - ts.replace(tzinfo=None)).total_seconds()) > TX_TIME_WINDOW_SECONDS * 2:
                        to_delete.append(tx_id)
                except Exception:
                    to_delete.append(tx_id)
            for tx_id in to_delete:
                SEEN_TX_IDS.pop(tx_id, None)


def _send_json(sock, obj):
    Protocol.send_lp_json(sock, obj)


def _recv_json(sock, max_size=65536):
    return Protocol.recv_lp_json(sock, max_size=max_size)


def broadcast_transaction(transaction_data):
    """Send NEW_TRANSACTION to registered peers (or NODE_PORTS fallback)."""
    message = {
        'type': 'NEW_TRANSACTION',
        'sender': transaction_data.get('sender', ''),
        'data': transaction_data.get('data', transaction_data),
        'signature': transaction_data.get('signature', ''),
        'public_key': transaction_data.get('public_key', ''),
        'relay': 'gateway',
    }
    raw = json.dumps(message).encode()
    endpoints_all, source = get_broadcast_targets()
    success = 0
    failures = []
    for host, port in endpoints_all:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect((host, port))
            sock.send(raw)
            sock.close()
            success += 1
            tx_id = transaction_data.get('data', {}).get('tx_id') if isinstance(transaction_data.get('data'), dict) else transaction_data.get('tx_id')
            _emit_gui_event(
                node_id=f"node_{port}",
                message=f"Outbound NEW_TRANSACTION to {host}:{port}",
                event_type='tx_broadcast',
                direction='outbound',
                status='sent',
                address=f"{host}:{port}",
                tx_id=tx_id,
            )
        except Exception as e:
            failures.append((host, port, str(e)))
            tx_id = transaction_data.get('data', {}).get('tx_id') if isinstance(transaction_data.get('data'), dict) else transaction_data.get('tx_id')
            _emit_gui_event(
                node_id=f"node_{port}",
                message=f"Broadcast failed to {host}:{port}: {e}",
                event_type='tx_broadcast',
                direction='outbound',
                status='error',
                address=f"{host}:{port}",
                tx_id=tx_id,
            )
    logger.info(
        "broadcast tx: %s/%s peer(s) ok active=%s source=%s",
        success,
        len(endpoints_all),
        len(endpoints_all),
        source,
    )
    for host, port, err in failures[:5]:
        logger.warning("broadcast tx fail %s:%s: %s", host, port, err)
    if len(failures) > 5:
        logger.warning("broadcast tx: %s additional peer errors omitted", len(failures) - 5)
    return success


def broadcast_stop_mining(block_index=None, block_hash=None):
    """Tell all active peers to stop mining (same target set as transaction broadcast)."""
    message = {
        'type': 'STOP_MINING',
        'block_index': block_index,
        'block_hash': block_hash,
    }
    raw = json.dumps(message).encode()
    endpoints_all, _ = get_broadcast_targets()
    for host, port in endpoints_all:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect((host, port))
            sock.send(raw)
            sock.close()
            _emit_gui_event(
                node_id=f"node_{port}",
                message=f"Outbound STOP_MINING to {host}:{port}",
                event_type='stop_mining',
                direction='outbound',
                status='sent',
                address=f"{host}:{port}",
                hash_value=block_hash,
            )
        except Exception:
            pass


def make_transaction(transaction_obj):
    """
    Accept a Transaction (or dict). Broadcast to all active peers.
    Returns (nodes_reached, peers_attemptecount).
    """
    if isinstance(transaction_obj, Transaction):
        payload = transaction_obj.to_mempool_dict()
    else:
        payload = transaction_obj if isinstance(transaction_obj, dict) else {}
    endpoints, _ = get_broadcast_targets()
    total = len(endpoints)
    count = broadcast_transaction(payload)
    return count, total


def notify_server(confirmation):
    """Send block_confirmation to the main server (marketplace)."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((SERVER_NOTIFY_HOST, SERVER_NOTIFY_PORT))
        raw = (json.dumps(confirmation) + '\n').encode()
        sock.send(raw)
        sock.close()
        logger.info("notified server: block_confirmation block_index=%s", confirmation.get('block_index'))
    except Exception as e:
        logger.warning("notify server failed: %s", e)


def _is_ed25519_public_key_b64(value):
    if not value or not isinstance(value, str):
        return False
    try:
        return len(base64.b64decode(value.encode())) == 32
    except Exception:
        return False


def _resolve_identity_public_key(cursor, identity, fallback_public_key=''):
    if identity and _is_ed25519_public_key_b64(identity):
        return identity
    if identity:
        try:
            cursor.execute('SELECT wallet_public_key FROM users WHERE username = ? LIMIT 1', (str(identity),))
            row = cursor.fetchone()
            if row and row['wallet_public_key'] and _is_ed25519_public_key_b64(row['wallet_public_key']):
                return row['wallet_public_key']
        except Exception:
            pass
        try:
            cursor.execute('SELECT public_key_hex FROM wallets WHERE username = ? LIMIT 1', (str(identity),))
            row = cursor.fetchone()
            if row and row['public_key_hex'] and _is_ed25519_public_key_b64(row['public_key_hex']):
                return row['public_key_hex']
        except Exception:
            pass
    if fallback_public_key and _is_ed25519_public_key_b64(fallback_public_key):
        return fallback_public_key
    return ''


def _lookup_username_by_public_key(cursor, public_key):
    if not public_key:
        return ''
    try:
        cursor.execute('SELECT username FROM users WHERE wallet_public_key = ? LIMIT 1', (public_key,))
        row = cursor.fetchone()
        if row and row['username']:
            return str(row['username'])
    except Exception:
        pass
    try:
        cursor.execute('SELECT username FROM wallets WHERE public_key_hex = ? LIMIT 1', (public_key,))
        row = cursor.fetchone()
        if row and row['username']:
            return str(row['username'])
    except Exception:
        pass
    return ''


def _normalize_tx_type(data):
    if not isinstance(data, dict):
        return ''
    raw = str(data.get('type') or data.get('action') or '').strip().upper()
    if raw in ('MINT', 'ASSET_MINT', 'UPLOAD'):
        return 'MINT'
    if raw in ('TRADE', 'BUY', 'ASSET_PURCHASE', 'PURCHASE'):
        return 'TRADE'
    return raw


def _normalize_state_tx(cursor, tx, state_snapshot):
    sender = tx.get('sender', '') if isinstance(tx, dict) else ''
    data = tx.get('data', {}) if isinstance(tx.get('data'), dict) else {}
    tx_id = data.get('tx_id', '')
    tx_ts = data.get('timestamp')
    public_key = tx.get('public_key', '') if isinstance(tx, dict) else ''
    signature = tx.get('signature', '') if isinstance(tx, dict) else ''
    if not tx_id or not tx_ts:
        return None, None, "missing tx_id/timestamp"
    if not public_key or not signature:
        return None, None, "missing tx signature/public_key"
    msg_bytes = _canonical_tx_message(sender, data)
    if not _verify_ed25519_signature(public_key, msg_bytes, signature):
        return None, None, "invalid tx signature"
    tx_type = _normalize_tx_type(data)
    image_hash = data.get('image_hash') or data.get('asset_hash')

    if tx_type == 'MINT':
        owner_hint = data.get('initial_owner') or data.get('owner_pub') or data.get('owner') or sender
        owner_pk = _resolve_identity_public_key(cursor, owner_hint, fallback_public_key=public_key)
        if not owner_pk:
            return None, None, "mint owner public key not resolved"
        state_tx = {'type': 'MINT', 'image_hash': image_hash, 'owner': owner_pk}
        meta = {
            'tx_type': 'MINT',
            'tx_id': tx_id,
            'image_hash': image_hash,
            'asset_name': data.get('asset_name') or '',
            'from_pk': owner_pk,
            'to_pk': owner_pk,
            'amount': 0.0,
        }
        return state_tx, meta, "ok"

    if tx_type == 'TRADE':
        buyer_hint = data.get('buyer') or data.get('buyer_pub') or data.get('from') or sender
        seller_hint = data.get('seller') or data.get('seller_pub') or data.get('to')
        buyer_pk = _resolve_identity_public_key(cursor, buyer_hint, fallback_public_key=public_key)
        seller_pk = _resolve_identity_public_key(cursor, seller_hint)
        if not seller_pk and image_hash:
            seller_pk = state_snapshot.ownership.get(image_hash, '')
        if not buyer_pk or not seller_pk:
            return None, None, "trade buyer/seller public key not resolved"
        amount_raw = data.get('price') if data.get('price') is not None else data.get('amount')
        try:
            price_int = StateManager.amount_to_int(amount_raw)
        except Exception:
            return None, None, "trade invalid price"
        state_tx = {
            'type': 'TRADE',
            'image_hash': image_hash,
            'buyer': buyer_pk,
            'seller': seller_pk,
            'price_int': price_int,
        }
        meta = {
            'tx_type': 'TRADE',
            'tx_id': tx_id,
            'image_hash': image_hash,
            'asset_name': data.get('asset_name') or '',
            'from_pk': buyer_pk,
            'to_pk': seller_pk,
            'amount': float(price_int) / 100.0,
        }
        return state_tx, meta, "ok"

    return None, None, f"unsupported tx type '{tx_type}'"


def _apply_state_tx(state_snapshot, state_tx):
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


def _sync_sql_balances_from_state(cursor, state_snapshot, timestamp):
    for public_key, amount_int in state_snapshot.balances.items():
        amount = float(amount_int) / 100.0
        try:
            cursor.execute(
                'UPDATE users SET wallet_balance = ?, wallet_updated_at = ? WHERE wallet_public_key = ?',
                (amount, timestamp, public_key),
            )
            cursor.execute(
                '''
                UPDATE users
                SET wallet_balance = ?, wallet_updated_at = ?
                WHERE username IN (
                    SELECT username FROM wallets WHERE public_key_hex = ?
                )
                ''',
                (amount, timestamp, public_key),
            )
        except Exception:
            continue


def _record_block_confirmation(confirmation, confirmations_count):
    global GATEWAY_STATE
    conn = None
    try:
        block_hash = confirmation.get('block_hash') or ''
        block_index = confirmation.get('block_index')
        miner_id = confirmation.get('miner_id') or ''
        timestamp = confirmation.get('timestamp') or datetime.now(timezone.utc).isoformat()
        tx_list = confirmation.get('transactions') or []

        conn = get_db_connection()
        cursor = conn.cursor()

        with STATE_LOCK:
            staged_state = GATEWAY_STATE.copy()
        tx_meta_list = []
        for tx in tx_list:
            state_tx, meta, reason = _normalize_state_tx(cursor, tx, staged_state)
            if not state_tx:
                return False, reason
            ok, reason = _apply_state_tx(staged_state, state_tx)
            if not ok:
                return False, reason
            tx_meta_list.append(meta)

        cursor.execute(
            '''INSERT OR IGNORE INTO blocks
               (block_hash, previous_hash, nonce, timestamp, miner_id, difficulty, transactions_count, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                block_hash,
                None,
                0,
                timestamp,
                miner_id,
                DEFAULT_POW_DIFFICULTY,
                len(tx_list),
                json.dumps(
                    {
                        'block_index': block_index,
                        'confirmations': confirmations_count,
                        'required_confirmations': CHAIN_CONFIRMATIONS_REQUIRED,
                        'transactions': tx_list,
                    }
                ),
            ),
        )
        cursor.execute('SELECT id FROM blocks WHERE block_hash = ?', (block_hash,))
        row = cursor.fetchone()
        block_id = row['id'] if row else None

        for meta in tx_meta_list:
            tx_hash_src = f"{meta['tx_type']}|{block_hash}|{meta['tx_id']}|{meta['image_hash']}"
            tx_hash = hashlib.sha256(tx_hash_src.encode()).hexdigest()
            cursor.execute(
                '''INSERT INTO transactions
                   (tx_hash, from_user, to_user, amount, timestamp, block_id, status, is_confirmed_on_chain)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tx_hash) DO UPDATE SET
                       from_user = excluded.from_user,
                       to_user = excluded.to_user,
                       amount = excluded.amount,
                       timestamp = excluded.timestamp,
                       block_id = excluded.block_id,
                       status = 'confirmed',
                       is_confirmed_on_chain = 1''',
                (
                    tx_hash,
                    meta['from_pk'],
                    meta['to_pk'],
                    float(meta['amount']),
                    timestamp,
                    block_id,
                    'confirmed',
                    1,
                ),
            )

            image_hash = meta.get('image_hash') or ''
            if not image_hash:
                continue

            if meta['tx_type'] == 'MINT':
                owner_pk = meta['to_pk']
                cursor.execute(
                    '''INSERT INTO assets (asset_id, asset_name, owner, block_hash, timestamp, is_confirmed_on_chain)
                       VALUES (?, ?, ?, ?, ?, 1)
                       ON CONFLICT(asset_id) DO UPDATE SET
                           owner = excluded.owner,
                           block_hash = excluded.block_hash,
                           timestamp = excluded.timestamp,
                           is_confirmed_on_chain = 1''',
                    (image_hash, meta.get('asset_name') or image_hash, owner_pk, block_hash, timestamp),
                )
                owner_username = _lookup_username_by_public_key(cursor, owner_pk)
                try:
                    cursor.execute(
                        '''
                        UPDATE marketplace_items
                        SET owner_public_key = ?, username = COALESCE(NULLIF(?, ''), username)
                        WHERE asset_hash = ?
                        ''',
                        (owner_pk, owner_username, image_hash),
                    )
                except Exception:
                    pass
                try:
                    cursor.execute(
                        '''
                        UPDATE not_approved_assets
                        SET owner_public_key = ?, username = COALESCE(NULLIF(?, ''), username)
                        WHERE asset_hash = ?
                        ''',
                        (owner_pk, owner_username, image_hash),
                    )
                except Exception:
                    pass

            if meta['tx_type'] == 'TRADE':
                buyer_pk = meta['from_pk']
                cursor.execute(
                    '''INSERT INTO assets (asset_id, asset_name, owner, block_hash, timestamp, is_confirmed_on_chain)
                       VALUES (?, ?, ?, ?, ?, 1)
                       ON CONFLICT(asset_id) DO UPDATE SET
                           owner = excluded.owner,
                           block_hash = excluded.block_hash,
                           timestamp = excluded.timestamp,
                           is_confirmed_on_chain = 1''',
                    (image_hash, meta.get('asset_name') or image_hash, buyer_pk, block_hash, timestamp),
                )
                buyer_username = _lookup_username_by_public_key(cursor, buyer_pk)
                try:
                    cursor.execute(
                        '''
                        UPDATE marketplace_items
                        SET owner_public_key = ?, username = COALESCE(NULLIF(?, ''), username), is_listed = 0, timestamp = ?
                        WHERE asset_hash = ?
                        ''',
                        (buyer_pk, buyer_username, timestamp, image_hash),
                    )
                except Exception:
                    pass

        _sync_sql_balances_from_state(cursor, staged_state, timestamp)
        conn.commit()
        with STATE_LOCK:
            GATEWAY_STATE = staged_state

        _append_gateway_ledger({
            'block_index': block_index,
            'block_hash': block_hash,
            'miner_id': miner_id,
            'timestamp': timestamp,
            'confirmations': confirmations_count,
            'required_confirmations': CHAIN_CONFIRMATIONS_REQUIRED,
            'transactions': tx_list,
        })
        return True, "ok"
    except Exception as e:
        try:
            if conn is not None:
                conn.rollback()
        except Exception:
            pass
        logger.warning("record block_confirmation failed: %s", e)
        return False, str(e)
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _append_gateway_ledger(block_entry):
    """Append a committed block summary to BLOCKCHAIN_DB/gateway/gateway_ledger.json."""
    try:
        ledger_path = Path(__file__).parent / "BLOCKCHAIN_DB" / "gateway" / "gateway_ledger.json"
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            existing = json.loads(ledger_path.read_text(encoding='utf-8'))
            if not isinstance(existing, list):
                existing = []
        except Exception:
            existing = []
        existing.append(block_entry)
        ledger_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding='utf-8')
    except Exception as e:
        logger.warning("_append_gateway_ledger failed: %s", e)


def _register_block_confirmation(msg):
    """Collect confirmations per (index,hash). Commit only after N confirmations."""
    try:
        block_index = int(msg.get('block_index'))
    except (TypeError, ValueError):
        return 'invalid', 0
    block_hash = msg.get('block_hash') or ''
    if not block_hash:
        return 'invalid', 0
    confirmer = msg.get('node_id') or msg.get('miner_id') or f"anon:{time.monotonic()}"

    with CONFIRMATION_LOCK:
        committed_hash = COMMITTED_BY_INDEX.get(block_index)
        if committed_hash:
            if committed_hash == block_hash:
                return 'already_committed', CHAIN_CONFIRMATIONS_REQUIRED
            return 'fork_rejected', 0

        key = (block_index, block_hash)
        bucket = BLOCK_CONFIRMATIONS.setdefault(key, {'nodes': set(), 'confirmation': msg})
        existing_txs = bucket.get('confirmation', {}).get('transactions') or []
        incoming_txs = msg.get('transactions') or []
        if json.dumps(existing_txs, sort_keys=True) != json.dumps(incoming_txs, sort_keys=True):
            return 'conflict', len(bucket['nodes'])
        bucket['confirmation'] = msg
        bucket['nodes'].add(confirmer)
        confirmations_count = len(bucket['nodes'])
        if confirmations_count < CHAIN_CONFIRMATIONS_REQUIRED:
            return 'pending', confirmations_count

        COMMITTED_BY_INDEX[block_index] = block_hash
        for other_key in list(BLOCK_CONFIRMATIONS.keys()):
            if other_key[0] == block_index and other_key != key:
                BLOCK_CONFIRMATIONS.pop(other_key, None)
        BLOCK_CONFIRMATIONS.pop(key, None)
        return 'ready', confirmations_count


def _ensure_gateway_ledger_dir():
    """Create BLOCKCHAIN_DB/gateway/ and an empty gateway_ledger.json if missing."""
    base = Path(__file__).parent / "BLOCKCHAIN_DB" / "gateway"
    base.mkdir(parents=True, exist_ok=True)
    ledger = base / "gateway_ledger.json"
    if not ledger.exists():
        ledger.write_text("[]", encoding="utf-8")
    logger.info("Gateway ledger dir: %s", base)


def _bootstrap_gateway_state_from_sql():
    """Initialize gateway read-cache state from current SQL snapshot."""
    global GATEWAY_STATE
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        boot_state = StateManager()
        try:
            cursor.execute(
                '''
                SELECT wallet_public_key, wallet_balance
                FROM users
                WHERE wallet_public_key IS NOT NULL AND wallet_public_key != ''
                '''
            )
            for row in cursor.fetchall() or []:
                pk = row['wallet_public_key']
                if not pk or not _is_ed25519_public_key_b64(pk):
                    continue
                balance_raw = row['wallet_balance']
                try:
                    bal_int = StateManager.amount_to_int(StateManager.INITIAL_COINS if balance_raw is None else balance_raw)
                except Exception:
                    base = StateManager.INITIAL_COINS if balance_raw is None else balance_raw
                    bal_int = int(float(base) * 100)
                boot_state.set_balance(pk, bal_int)
        except Exception:
            pass
        try:
            cursor.execute(
                '''
                SELECT w.public_key_hex, u.wallet_balance
                FROM wallets w
                LEFT JOIN users u ON u.username = w.username
                WHERE w.public_key_hex IS NOT NULL AND w.public_key_hex != ''
                '''
            )
            for row in cursor.fetchall() or []:
                pk = row['public_key_hex']
                if not pk or not _is_ed25519_public_key_b64(pk):
                    continue
                if pk in boot_state.balances:
                    continue
                balance_raw = row['wallet_balance']
                if balance_raw in (None, ''):
                    bal_int = StateManager.INITIAL_BALANCE_INT
                else:
                    try:
                        bal_int = StateManager.amount_to_int(balance_raw)
                    except Exception:
                        bal_int = int(float(balance_raw) * 100)
                boot_state.set_balance(pk, bal_int)
        except Exception:
            pass
        try:
            cursor.execute(
                '''
                SELECT asset_hash, owner_public_key
                FROM marketplace_items
                WHERE asset_hash IS NOT NULL AND asset_hash != ''
                '''
            )
            for row in cursor.fetchall() or []:
                asset_hash = row['asset_hash']
                owner_pk = row['owner_public_key']
                if asset_hash and owner_pk and _is_ed25519_public_key_b64(owner_pk):
                    boot_state.ownership[asset_hash] = owner_pk
        except Exception:
            pass
        with STATE_LOCK:
            GATEWAY_STATE = boot_state
        logger.info(
            "gateway state bootstrap complete balances=%s ownership=%s",
            len(boot_state.balances),
            len(boot_state.ownership),
        )
    except Exception as e:
        logger.warning("gateway state bootstrap failed: %s", e)
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:
            pass


def _bootstrap_committed_indexes_from_ledger():
    """Load already-committed block indexes so confirmations stay idempotent across restarts."""
    global COMMITTED_BY_INDEX
    ledger_path = Path(__file__).parent / "BLOCKCHAIN_DB" / "gateway" / "gateway_ledger.json"
    committed = {}
    try:
        entries = json.loads(ledger_path.read_text(encoding='utf-8'))
        if not isinstance(entries, list):
            entries = []
    except Exception:
        entries = []
    for entry in entries:
        try:
            idx = int(entry.get('block_index'))
            h = str(entry.get('block_hash') or '')
            if h:
                committed[idx] = h
        except Exception:
            continue
    with CONFIRMATION_LOCK:
        COMMITTED_BY_INDEX = committed
    logger.info("loaded committed indexes from gateway ledger: %s", len(committed))


def run_server(stop_event=None, gui_bridge=None):
    if gui_bridge is not None:
        set_gui_bridge(gui_bridge)
    _ensure_gateway_ledger_dir()
    _bootstrap_committed_indexes_from_ledger()
    init_database()
    _bootstrap_gateway_state_from_sql()
    _emit_gui_event(message="Gateway server starting", event_type='gateway', direction='system', status='starting')
    logger.info(
        "Gateway starting; NODE_PORTS fallback=%s (used until peers register)",
        NODE_PORTS,
    )
    threading.Thread(target=_cleanup_seen_tx_ids, daemon=True).start()
    threading.Thread(target=_registry_reaper_loop, daemon=True).start()
    # Single listener: clients send action=submit_transaction, /buy, or health; nodes send type=block_confirmation
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((RPC_LISTEN_HOST, RPC_LISTEN_PORT))
    server.listen(5)
    server.settimeout(1.0)
    logger.info(
        "Gateway listening on %s:%s (clients: submit_transaction,/buy,health; nodes: block_confirmation)",
        RPC_LISTEN_HOST,
        RPC_LISTEN_PORT,
    )
    _emit_gui_event(
        message=f"Gateway listening on {RPC_LISTEN_HOST}:{RPC_LISTEN_PORT}",
        event_type='gateway',
        direction='system',
        status='listening',
        address=f"{RPC_LISTEN_HOST}:{RPC_LISTEN_PORT}",
    )

    def handle(conn, addr):
        try:
            conn.settimeout(15)
            msg = _recv_json(conn)
            if not msg:
                conn.close()
                return
            if msg.get('type') == 'block_confirmation':
                status, confirmations_count = _register_block_confirmation(msg)

                # Stop miners as soon as first valid block candidate appears.
                if status in ('pending', 'ready', 'already_committed'):
                    broadcast_stop_mining(
                        block_index=msg.get('block_index'),
                        block_hash=msg.get('block_hash'),
                    )

                if status == 'invalid':
                    _send_json(conn, {'status': 'failed', 'reason': 'invalid block_confirmation payload'})
                    conn.close()
                    return
                if status == 'fork_rejected':
                    _send_json(conn, {'status': 'rejected', 'reason': 'fork index already committed'})
                    conn.close()
                    return
                if status == 'conflict':
                    _send_json(conn, {'status': 'rejected', 'reason': 'confirmation payload conflict'})
                    conn.close()
                    return
                if status == 'pending':
                    _send_json(
                        conn,
                        {
                            'status': 'pending',
                            'confirmations': confirmations_count,
                            'required_confirmations': CHAIN_CONFIRMATIONS_REQUIRED,
                        },
                    )
                    conn.close()
                    return
                if status == 'already_committed':
                    _send_json(
                        conn,
                        {
                            'status': 'ok',
                            'message': 'already committed',
                            'confirmations': CHAIN_CONFIRMATIONS_REQUIRED,
                            'required_confirmations': CHAIN_CONFIRMATIONS_REQUIRED,
                        },
                    )
                    conn.close()
                    return

                logger.info(
                    "=== BLOCK COMMITTED === block_index=%s block_hash=%s miner_id=%s node_id=%s confirmations=%s/%s timestamp=%s",
                    msg.get('block_index'),
                    msg.get('block_hash'),
                    msg.get('miner_id'),
                    msg.get('node_id'),
                    confirmations_count,
                    CHAIN_CONFIRMATIONS_REQUIRED,
                    msg.get('timestamp'),
                )
                _emit_gui_event(
                    node_id=msg.get('node_id') or msg.get('miner_id') or '',
                    message=f"Block committed index={msg.get('block_index')} hash={msg.get('block_hash', '')}",
                    event_type='block_confirmation',
                    direction='inbound',
                    status='confirmed',
                    tx_id=((msg.get('transactions') or [{}])[0].get('data', {}) or {}).get('tx_id') if msg.get('transactions') else '',
                    hash_value=msg.get('block_hash'),
                )

                ok, reason = _record_block_confirmation(msg, confirmations_count)
                if not ok:
                    try:
                        idx = int(msg.get('block_index'))
                        with CONFIRMATION_LOCK:
                            COMMITTED_BY_INDEX.pop(idx, None)
                    except Exception:
                        pass
                    _send_json(conn, {'status': 'failed', 'reason': reason})
                    conn.close()
                    return

                notify_server(msg)
                _send_json(
                    conn,
                    {
                        'status': 'ok',
                        'confirmations': confirmations_count,
                        'required_confirmations': CHAIN_CONFIRMATIONS_REQUIRED,
                    },
                )
                conn.close()
                return
            mtype = msg.get('type')
            if mtype in ('node_register', 'node_ping'):
                host = msg.get('host')
                port = msg.get('port')
                node_id = msg.get('node_id', '') or ''
                if port is None:
                    _send_json(conn, {'status': 'failed', 'message': 'missing port'})
                    conn.close()
                    return
                if register_peer(host, port, node_id):
                    endpoints, src = get_broadcast_targets()
                    _send_json(conn, {
                        'status': 'ok',
                        'registered': True,
                        'type': 'node_registered',
                        'active_peers': len(endpoints),
                        'peer_source': src,
                    })
                else:
                    _send_json(conn, {'status': 'failed', 'message': 'invalid registration'})
                conn.close()
                return
            action = msg.get('action')
            if action == 'health':
                endpoints, src = get_broadcast_targets()
                _send_json(conn, {
                    'status': 'ok',
                    'service': 'gateway_server',
                    'active_peers': len(endpoints),
                    'peer_source': src,
                })
                conn.close()
                return
            if action in ('/buy', 'buy', 'submit_purchase'):
                body = msg.get('body') or {}
                required = ['buyer', 'price', 'timestamp', 'tx_id', 'public_key', 'signature']
                missing = [k for k in required if k not in body or body.get(k) in (None, '')]
                if missing:
                    _send_json(conn, {'status': 'failed', 'message': f"Missing fields: {', '.join(missing)}"})
                    conn.close()
                    return
                if not body.get('asset_id') and not body.get('asset_hash'):
                    _send_json(conn, {'status': 'failed', 'message': 'Missing asset_id/asset_hash'})
                    conn.close()
                    return

                buyer = body.get('buyer')
                asset_id = body.get('asset_id')
                asset_name = body.get('asset_name') or ''
                try:
                    price = float(body.get('price'))
                except (TypeError, ValueError):
                    _send_json(conn, {'status': 'failed', 'message': 'Invalid price'})
                    conn.close()
                    return
                ts = body.get('timestamp')
                tx_id = body.get('tx_id')
                signature = body.get('signature')
                public_key = body.get('public_key')
                asset_hash = body.get('asset_hash')
                buyer_pub = body.get('buyer_pub') or public_key
                seller_pub = body.get('seller_pub') or ''
                seller_name = body.get('seller') or ''

                if not _is_timestamp_valid(ts):
                    _send_json(conn, {'status': 'failed', 'message': 'Invalid or stale timestamp'})
                    conn.close()
                    return
                ok, reason = _register_tx_id(tx_id, ts)
                if not ok:
                    _send_json(conn, {'status': 'failed', 'message': reason})
                    conn.close()
                    return

                db_conn = None
                try:
                    db_conn = get_db_connection()
                    cursor = db_conn.cursor()

                    row = None
                    if asset_id not in (None, ''):
                        cursor.execute(
                            '''
                            SELECT id, asset_hash, owner_public_key, username
                            FROM marketplace_items
                            WHERE id = ?
                            LIMIT 1
                            ''',
                            (str(asset_id),),
                        )
                        row = cursor.fetchone()
                    if row is None and asset_hash:
                        cursor.execute(
                            '''
                            SELECT id, asset_hash, owner_public_key, username
                            FROM marketplace_items
                            WHERE asset_hash = ?
                            LIMIT 1
                            ''',
                            (asset_hash,),
                        )
                        row = cursor.fetchone()

                    resolved_asset_id = str(row['id']) if row and row['id'] is not None else (str(asset_id) if asset_id not in (None, '') else '')
                    resolved_asset_hash = (row['asset_hash'] if row and row['asset_hash'] else asset_hash) or ''
                    if not resolved_asset_hash:
                        _send_json(conn, {'status': 'failed', 'message': 'Asset hash not found'})
                        conn.close()
                        return

                    buyer_pk = _resolve_identity_public_key(cursor, buyer_pub or buyer, fallback_public_key=public_key)
                    seller_pk = _resolve_identity_public_key(cursor, seller_pub or seller_name)
                    if not seller_pk and row is not None:
                        seller_pk = _resolve_identity_public_key(cursor, row['owner_public_key'] or row['username'])
                    if not buyer_pk or not seller_pk:
                        _send_json(conn, {'status': 'failed', 'message': 'Unable to resolve buyer/seller public keys'})
                        conn.close()
                        return
                finally:
                    try:
                        if db_conn is not None:
                            db_conn.close()
                    except Exception:
                        pass

                tx_payload = {
                    'type': 'TRADE',
                    'action': 'asset_purchase',
                    'tx_id': tx_id,
                    'asset_id': resolved_asset_id,
                    'image_hash': resolved_asset_hash,
                    'asset_hash': resolved_asset_hash,
                    'asset_name': asset_name,
                    'buyer': buyer_pk,
                    'seller': seller_pk,
                    'buyer_pub': buyer_pk,
                    'seller_pub': seller_pk,
                    'price': price,
                    'amount': price,
                    'timestamp': ts,
                }

                sender_identity = buyer_pk
                msg_bytes = _canonical_tx_message(sender_identity, tx_payload)
                if not _verify_ed25519_signature(public_key, msg_bytes, signature):
                    _send_json(conn, {'status': 'failed', 'message': 'Invalid signature'})
                    conn.close()
                    return

                tx = Transaction(sender=sender_identity, data=tx_payload, signature=signature, public_key=public_key)
                _emit_gui_event(
                    node_id='gateway',
                    message=f"Inbound purchase request from {buyer}",
                    event_type='purchase',
                    direction='inbound',
                    status='received',
                    tx_id=tx_id,
                )
                count, _ = make_transaction(tx)
                status_msg = "Transaction submitted. Broadcast to %s node(s). Pending confirmation." % count
                if count == 0:
                    status_msg = "Transaction failed: no nodes reached. Start nodes first."
                _send_json(
                    conn,
                    {
                        'status': 'submitted' if count else 'failed',
                        'nodes_reached': count,
                        'message': status_msg,
                        'timestamp': ts,
                        'transaction': {'sender': sender_identity, 'data': tx_payload},
                    },
                )
                conn.close()
                return
            if action == 'submit_transaction':
                body = msg.get('body') or msg
                if not body:
                    _send_json(conn, {'error': 'Invalid or missing body'})
                else:
                    ts = datetime.now(timezone.utc).isoformat()
                    logger.info(
                        "=== TRANSACTION SUBMITTED === timestamp=%s sender=%s data=%s signature=%s",
                        ts,
                        body.get('sender'),
                        body.get('data'),
                        body.get('signature'),
                    )
                    sender = body.get('sender', '')
                    data = body.get('data', {}) or {}
                    signature = body.get('signature', '')
                    public_key = body.get('public_key', '')

                    tx_id = data.get('tx_id') if isinstance(data, dict) else None
                    tx_ts = data.get('timestamp') if isinstance(data, dict) else None
                    if not tx_id or not tx_ts:
                        _send_json(conn, {'status': 'failed', 'message': 'Missing tx_id/timestamp'})
                        conn.close()
                        return
                    if not _is_timestamp_valid(tx_ts):
                        _send_json(conn, {'status': 'failed', 'message': 'Invalid or stale timestamp'})
                        conn.close()
                        return
                    ok, reason = _register_tx_id(tx_id, tx_ts)
                    if not ok:
                        _send_json(conn, {'status': 'failed', 'message': reason})
                        conn.close()
                        return
                    msg_bytes = _canonical_tx_message(sender, data)
                    if not _verify_ed25519_signature(public_key, msg_bytes, signature):
                        _send_json(conn, {'status': 'failed', 'message': 'Invalid signature'})
                        conn.close()
                        return

                    _emit_gui_event(
                        node_id='gateway',
                        message=f"Inbound submit_transaction from {sender}",
                        event_type='submit_transaction',
                        direction='inbound',
                        status='received',
                        tx_id=tx_id,
                    )
                    count, _ = make_transaction(body)
                    # Don't say "3/5 nodes" - say tx submitted and how many nodes got it
                    status_msg = "Transaction submitted. Broadcast to %s node(s). Pending confirmation." % count
                    if count == 0:
                        status_msg = "Transaction failed: no nodes reached. Start nodes first."
                    _send_json(
                        conn,
                        {
                            'status': 'submitted' if count else 'failed',
                            'nodes_reached': count,
                            'message': status_msg,
                            'timestamp': ts,
                            'transaction': {'sender': body.get('sender'), 'data': body.get('data')},
                        },
                    )
                conn.close()
                return
            _send_json(conn, {'error': f'Unknown action or type: {action or msg.get("type")}'})
            conn.close()
        except Exception as e:
            logger.exception("handle %s: %s", addr, e)
            try:
                conn.close()
            except Exception:
                pass

    while stop_event is None or not stop_event.is_set():
        try:
            client, addr = server.accept()
            threading.Thread(target=handle, args=(client, addr), daemon=True).start()
        except KeyboardInterrupt:
            break
        except socket.timeout:
            continue
        except Exception as e:
            logger.error("accept: %s", e)
    server.close()
    _emit_gui_event(message="Gateway server stopped", event_type='gateway', direction='system', status='stopped')
    logger.info("Gateway server stopped")


def main():
    parser = argparse.ArgumentParser(description="Aurex Gateway Server")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run gateway server without the Tk dashboard.",
    )
    args = parser.parse_args()
    if args.headless:
        run_server()
        return
    try:
        from gateway_dashboard import GatewayDashboard
        GatewayDashboard().run()
    except Exception as e:
        logger.warning("Dashboard launch failed (%s). Falling back to headless mode.", e)
        run_server()


if __name__ == '__main__':
    main()

