"""
Gateway Server - Socket-based entry point (no Flask).
- Listens for submit_transaction and health on RPC_LISTEN_PORT.
- Receives block_confirmation from nodes and forwards to main server.
"""

import json
import socket
import sys
import os
import threading
import struct
import logging
import hashlib
from datetime import datetime
from pathlib import Path
import base64
import time
import random

sys.path.insert(0, os.path.dirname(__file__))

from config import (
    NODE_PORTS,
    RPC_HOST,
    RPC_LISTEN_HOST,
    RPC_LISTEN_PORT,
    SERVER_NOTIFY_HOST,
    SERVER_NOTIFY_PORT,
    DEFAULT_SOCKET_TIMEOUT,
    SOCKET_BUFFER_SIZE,
    DEFAULT_POW_DIFFICULTY,
    TX_TIME_WINDOW_SECONDS,
    NODE_REGISTRY_STALE_SECONDS,
    NODE_REGISTRY_REAP_INTERVAL_SECONDS,
    GOSSIP_FANOUT,
)
from models import Transaction
from db_init import get_db_connection, init_database
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

# (host, port) -> {'node_id': str, 'last_seen': monotonic time}
NODE_REGISTRY = {}
NODE_REGISTRY_LOCK = threading.Lock()


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
    return True


def _prune_stale_peers():
    cutoff = time.monotonic() - NODE_REGISTRY_STALE_SECONDS
    with NODE_REGISTRY_LOCK:
        dead = [k for k, v in NODE_REGISTRY.items() if v.get('last_seen', 0) < cutoff]
        for k in dead:
            NODE_REGISTRY.pop(k, None)
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




def _select_fanout(endpoints):
    if not endpoints:
        return []
    if GOSSIP_FANOUT and len(endpoints) > GOSSIP_FANOUT:
        return random.sample(endpoints, GOSSIP_FANOUT)
    return endpoints
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
        now = datetime.utcnow()
        delta = abs((now - ts.replace(tzinfo=None)).total_seconds())
        return delta <= TX_TIME_WINDOW_SECONDS
    except Exception:
        return False


def _register_tx_id(tx_id, ts_str):
    if not tx_id:
        return False, "missing tx_id"
    with SEEN_TX_LOCK:
        if tx_id in SEEN_TX_IDS:
            return False, "duplicate tx_id"
        SEEN_TX_IDS[tx_id] = ts_str or datetime.utcnow().isoformat()
    return True, "ok"


def _cleanup_seen_tx_ids():
    while True:
        time.sleep(max(30, TX_TIME_WINDOW_SECONDS))
        cutoff = datetime.utcnow()
        with SEEN_TX_LOCK:
            to_delete = []
            for tx_id, ts_str in SEEN_TX_IDS.items():
                try:
                    ts = datetime.fromisoformat(ts_str)
                    if abs((cutoff - ts).total_seconds()) > TX_TIME_WINDOW_SECONDS * 2:
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
    endpoints = _select_fanout(endpoints_all)
    success = 0
    failures = []
    for host, port in endpoints:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect((host, port))
            sock.send(raw)
            sock.close()
            success += 1
        except Exception as e:
            failures.append((host, port, str(e)))
    logger.info(
        "broadcast tx: %s/%s peer(s) ok active=%s source=%s",
        success,
        len(endpoints),
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

def _record_block_confirmation(confirmation):
    try:
        block_hash = confirmation.get('block_hash') or ''
        block_index = confirmation.get('block_index')
        miner_id = confirmation.get('miner_id') or ''
        timestamp = confirmation.get('timestamp') or datetime.utcnow().isoformat()
        tx_list = confirmation.get('transactions') or []

        conn = get_db_connection()
        cursor = conn.cursor()
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
                json.dumps({'block_index': block_index, 'transactions': tx_list}),
            ),
        )
        cursor.execute('SELECT id FROM blocks WHERE block_hash = ?', (block_hash,))
        row = cursor.fetchone()
        block_id = row['id'] if row else None

        for tx in tx_list:
            data = tx.get('data') if isinstance(tx.get('data'), dict) else {}
            action = data.get('action', '')
            tx_id = data.get('tx_id', '')

            # ── MINT: new asset registered on-chain ───────────────────────────
            if action == 'asset_mint':
                asset_hash = data.get('asset_hash', '')
                asset_name = data.get('asset_name', '')
                initial_owner = data.get('owner') or tx.get('sender', '')
                initial_owner_pk = data.get('owner_pub', '')
                tx_hash_src = f"MINT|{block_hash}|{asset_hash}|{initial_owner}|{tx_id}"
                tx_hash = hashlib.sha256(tx_hash_src.encode()).hexdigest()
                cursor.execute(
                    '''INSERT OR IGNORE INTO transactions
                       (tx_hash, from_user, to_user, amount, timestamp, block_id, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (tx_hash, initial_owner, initial_owner, 0.0, timestamp, block_id, 'confirmed'),
                )
                if asset_hash and asset_name and initial_owner:
                    cursor.execute(
                        '''INSERT OR IGNORE INTO assets
                           (asset_id, asset_name, owner, block_hash, timestamp)
                           VALUES (?, ?, ?, ?, ?)''',
                        (asset_hash, asset_name, initial_owner, block_hash, timestamp),
                    )
                logger.info(
                    "MINT confirmed: asset_hash=%s owner=%s pk=%s...",
                    asset_hash[:16] if asset_hash else '?',
                    initial_owner,
                    initial_owner_pk[:16] if initial_owner_pk else '?',
                )
                continue

            # ── PURCHASE: buyer pays seller, buyer gets asset ownership ────────
            if action == 'purchase':
                buyer = data.get('from') or tx.get('sender', '')  # buyer pays
                seller = data.get('to') or ''                      # seller receives money
                amount = float(data.get('amount') or data.get('price') or 0)
                asset_id = data.get('asset_id', '')
                asset_hash = data.get('asset_hash', '')
                asset_name = data.get('asset_name', '')
                tx_hash_src = f"PURCHASE|{block_hash}|{buyer}|{seller}|{amount}|{tx_id}"
                tx_hash = hashlib.sha256(tx_hash_src.encode()).hexdigest()
                cursor.execute(
                    '''INSERT OR IGNORE INTO transactions
                       (tx_hash, from_user, to_user, amount, timestamp, block_id, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (tx_hash, buyer, seller, amount, timestamp, block_id, 'confirmed'),
                )
                # buyer becomes the new asset owner
                if buyer and (asset_id or asset_hash):
                    ref = asset_hash or asset_id
                    cursor.execute(
                        '''UPDATE assets SET owner = ?, block_hash = ?, timestamp = ?
                           WHERE asset_id = ?''',
                        (buyer, block_hash, timestamp, ref),
                    )
                logger.info(
                    "PURCHASE confirmed: buyer=%s seller=%s asset=%s amount=%.2f",
                    buyer, seller, asset_id or asset_hash, amount,
                )
                continue

            # ── ASSET_TRANSFER: non-monetary ownership transfer ────────────────
            if action == 'asset_transfer':
                from_user = data.get('from') or tx.get('sender', '')
                to_user = data.get('to') or ''
                amount = float(data.get('amount') or data.get('price') or 0)
                asset_id = data.get('asset_id', '')
                asset_hash = data.get('asset_hash', '')
                asset_name = data.get('asset_name', '')
                tx_hash_src = f"TRANSFER|{block_hash}|{from_user}|{to_user}|{amount}|{tx_id}"
                tx_hash = hashlib.sha256(tx_hash_src.encode()).hexdigest()
                cursor.execute(
                    '''INSERT OR IGNORE INTO transactions
                       (tx_hash, from_user, to_user, amount, timestamp, block_id, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?)''',
                    (tx_hash, from_user, to_user, amount, timestamp, block_id, 'confirmed'),
                )
                # to_user becomes new owner
                if to_user and (asset_id or asset_hash):
                    ref = asset_hash or asset_id
                    cursor.execute(
                        '''UPDATE assets SET owner = ?, block_hash = ?, timestamp = ?
                           WHERE asset_id = ?''',
                        (to_user, block_hash, timestamp, ref),
                    )
                logger.info(
                    "ASSET_TRANSFER confirmed: from=%s to=%s asset=%s",
                    from_user, to_user, asset_id or asset_hash,
                )
                continue

            # ── Generic fallback ──────────────────────────────────────────────
            from_user = data.get('from') or tx.get('sender') or ''
            to_user = data.get('to') or data.get('seller') or ''
            amount = data.get('amount') if data.get('amount') is not None else data.get('price') or 0
            tx_hash_src = f"{block_hash}|{from_user}|{to_user}|{amount}|{tx_id}"
            tx_hash = hashlib.sha256(tx_hash_src.encode()).hexdigest()
            cursor.execute(
                '''INSERT OR IGNORE INTO transactions
                   (tx_hash, from_user, to_user, amount, timestamp, block_id, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (tx_hash, from_user, to_user, float(amount), timestamp, block_id, 'confirmed'),
            )

        conn.commit()
        conn.close()

        # ── Write a human-readable snapshot to gateway_ledger.json ───────────
        _append_gateway_ledger({
            'block_index': block_index,
            'block_hash': block_hash,
            'miner_id': miner_id,
            'timestamp': timestamp,
            'transactions': tx_list,
        })

    except Exception as e:
        logger.warning("record block_confirmation failed: %s", e)


def _append_gateway_ledger(block_entry):
    """Append a confirmed block summary to BLOCKCHAIN_DB/gateway/gateway_ledger.json."""
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


def _ensure_gateway_ledger_dir():
    """Create BLOCKCHAIN_DB/gateway/ and an empty gateway_ledger.json if missing."""
    base = Path(__file__).parent / "BLOCKCHAIN_DB" / "gateway"
    base.mkdir(parents=True, exist_ok=True)
    ledger = base / "gateway_ledger.json"
    if not ledger.exists():
        ledger.write_text("[]", encoding="utf-8")
    logger.info("Gateway ledger dir: %s", base)


def main():
    _ensure_gateway_ledger_dir()
    init_database()
    logger.info(
        "Gateway starting; NODE_PORTS fallback=%s (used until peers register)",
        NODE_PORTS,
    )
    threading.Thread(target=_cleanup_seen_tx_ids, daemon=True).start()
    threading.Thread(target=_registry_reaper_loop, daemon=True).start()
    # Single listener: clients send action=submit_transaction or action=health; nodes send type=block_confirmation
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((RPC_LISTEN_HOST, RPC_LISTEN_PORT))
    server.listen(5)
    logger.info(
        "Gateway listening on %s:%s (clients: submit_transaction/health; nodes: block_confirmation)",
        RPC_LISTEN_HOST,
        RPC_LISTEN_PORT,
    )

    def handle(conn, addr):
        try:
            conn.settimeout(15)
            msg = _recv_json(conn)
            if not msg:
                conn.close()
                return
            if msg.get('type') == 'block_confirmation':
                logger.info(
                    "=== TRANSACTION CONFIRMED (block committed) === block_index=%s block_hash=%s miner_id=%s node_id=%s timestamp=%s",
                    msg.get('block_index'),
                    msg.get('block_hash'),
                    msg.get('miner_id'),
                    msg.get('node_id'),
                    msg.get('timestamp'),
                )
                logger.info("Saved to ledger: block_index=%s", msg.get('block_index'))
                _record_block_confirmation(msg)
                notify_server(msg)
                broadcast_stop_mining(
                    block_index=msg.get('block_index'),
                    block_hash=msg.get('block_hash'),
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
            if action == 'submit_purchase':
                body = msg.get('body') or {}
                required = ['buyer', 'seller', 'asset_id', 'asset_name', 'price', 'timestamp', 'tx_id', 'public_key', 'signature']
                missing = [k for k in required if k not in body or body.get(k) in (None, '')]
                if missing:
                    _send_json(conn, {'status': 'failed', 'message': f"Missing fields: {', '.join(missing)}"})
                    conn.close()
                    return

                buyer = body.get('buyer')
                seller = body.get('seller')
                asset_id = body.get('asset_id')
                asset_name = body.get('asset_name')
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

                if not _is_timestamp_valid(ts):
                    _send_json(conn, {'status': 'failed', 'message': 'Invalid or stale timestamp'})
                    conn.close()
                    return
                ok, reason = _register_tx_id(tx_id, ts)
                if not ok:
                    _send_json(conn, {'status': 'failed', 'message': reason})
                    conn.close()
                    return
                tx_payload = {
                    'action': 'purchase',
                    'tx_id': tx_id,
                    'asset_id': asset_id,
                    'asset_hash': asset_hash,
                    'asset_name': asset_name,
                    'price': price,
                    'from': buyer,
                    'to': seller,
                    'amount': price,
                    'timestamp': ts,
                }

                msg_bytes = _canonical_tx_message(buyer, tx_payload)
                if not _verify_ed25519_signature(public_key, msg_bytes, signature):
                    _send_json(conn, {'status': 'failed', 'message': 'Invalid signature'})
                    conn.close()
                    return

                tx = Transaction(sender=buyer, data=tx_payload, signature=signature, public_key=public_key)
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
                        'transaction': {'sender': buyer, 'data': tx_payload},
                    },
                )
                conn.close()
                return
            if action == 'submit_transaction':
                body = msg.get('body') or msg
                if not body:
                    _send_json(conn, {'error': 'Invalid or missing body'})
                else:
                    from datetime import datetime

                    ts = datetime.utcnow().isoformat()
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

    while True:
        try:
            client, addr = server.accept()
            threading.Thread(target=handle, args=(client, addr), daemon=True).start()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error("accept: %s", e)
    server.close()
    logger.info("Gateway server stopped")


if __name__ == '__main__':
    main()

