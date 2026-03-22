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
    DEFAULT_SOCKET_TIMEOUT,
    SOCKET_BUFFER_SIZE,
    DEFAULT_POW_DIFFICULTY,
    TX_TIME_WINDOW_SECONDS,
)
from models import Transaction
from db_init import get_db_connection, init_database
from cryptography.hazmat.primitives.asymmetric import ed25519

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
        ts = datetime.fromisoformat(ts_str)
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
    raw = json.dumps(obj).encode()
    sock.send(struct.pack('>H', len(raw)) + raw)


def _recv_json(sock, max_size=65536):
    try:
        len_buf = sock.recv(2)
        if len(len_buf) < 2:
            return None
        (size,) = struct.unpack('>H', len_buf)
        if size > max_size:
            return None
        data = b''
        while len(data) < size:
            chunk = sock.recv(min(size - len(data), 4096))
            if not chunk:
                return None
            data += chunk
        return json.loads(data.decode())
    except Exception:
        return None


def broadcast_transaction(transaction_data):
    """Send NEW_TRANSACTION to all node ports. Returns count of nodes that accepted."""
    message = {
        'type': 'NEW_TRANSACTION',
        'sender': transaction_data.get('sender', ''),
        'data': transaction_data.get('data', transaction_data),
        'signature': transaction_data.get('signature', ''),
        'public_key': transaction_data.get('public_key', ''),
    }
    raw = json.dumps(message).encode()
    success = 0
    for port in NODE_PORTS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect((RPC_HOST, port))
            sock.send(raw)
            sock.close()
            success += 1
            logger.info("broadcast tx to node port=%s", port)
        except Exception as e:
            logger.warning("node port=%s: %s", port, e)
    return success


def broadcast_stop_mining(block_index=None, block_hash=None):
    """Tell all nodes to stop mining (safety stop after a block is confirmed)."""
    message = {
        'type': 'STOP_MINING',
        'block_index': block_index,
        'block_hash': block_hash,
    }
    raw = json.dumps(message).encode()
    for port in NODE_PORTS:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(SOCKET_TIMEOUT)
            sock.connect((RPC_HOST, port))
            sock.send(raw)
            sock.close()
        except Exception:
            pass


def make_transaction(transaction_obj):
    """
    Accept a Transaction (or dict). Broadcast to all nodes to start mining race.
    Returns (nodes_reached, total_nodes).
    """
    if isinstance(transaction_obj, Transaction):
        payload = transaction_obj.to_mempool_dict()
    else:
        payload = transaction_obj if isinstance(transaction_obj, dict) else {}
    count = broadcast_transaction(payload)
    return count, len(NODE_PORTS)


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
                json.dumps({'block_index': confirmation.get('block_index'), 'transactions': tx_list}),
            ),
        )
        cursor.execute('SELECT id FROM blocks WHERE block_hash = ?', (block_hash,))
        row = cursor.fetchone()
        block_id = row['id'] if row else None

        for tx in tx_list:
            data = tx.get('data') if isinstance(tx.get('data'), dict) else {}
            from_user = data.get('from') or tx.get('sender') or ''
            to_user = data.get('to') or data.get('seller')
            amount = data.get('amount') if data.get('amount') is not None else data.get('price') or 0
            tx_id = data.get('tx_id', '')
            tx_hash_src = f"{block_hash}|{from_user}|{to_user}|{amount}|{tx_id}"
            tx_hash = hashlib.sha256(tx_hash_src.encode()).hexdigest()
            cursor.execute(
                '''INSERT OR IGNORE INTO transactions
                   (tx_hash, from_user, to_user, amount, timestamp, block_id, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (tx_hash, from_user, to_user, float(amount), timestamp, block_id, 'confirmed'),
            )

            asset_id = data.get('asset_id')
            asset_name = data.get('asset_name')
            if asset_id and asset_name and to_user:
                cursor.execute(
                    '''INSERT OR REPLACE INTO assets
                       (asset_id, asset_name, owner, block_hash, timestamp)
                       VALUES (?, ?, ?, ?, ?)''',
                    (str(asset_id), asset_name, to_user, block_hash, timestamp),
                )

        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning("record block_confirmation failed: %s", e)


def main():
    init_database()
    logger.info("Gateway server starting (socket, no Flask); submit_transaction -> nodes %s", NODE_PORTS)
    threading.Thread(target=_cleanup_seen_tx_ids, daemon=True).start()
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
            action = msg.get('action')
            if action == 'health':
                _send_json(conn, {'status': 'ok', 'service': 'gateway_server'})
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

