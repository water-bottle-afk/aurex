"""
RPC Server - Socket-based entry point (no Flask).
- Listens for submit_transaction and health on RPC_LISTEN_PORT.
- Background thread listens for block_confirmation from nodes; forwards to main server.
"""

import json
import socket
import sys
import os
import threading
import struct
import logging

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
)
from models import Transaction

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('rpc_server')

SOCKET_TIMEOUT = 3


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


def main():
    logger.info("RPC server starting (socket, no Flask); submit_transaction -> nodes %s", NODE_PORTS)
    # Single listener: clients send action=submit_transaction or action=health; nodes send type=block_confirmation
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((RPC_LISTEN_HOST, RPC_LISTEN_PORT))
    server.listen(5)
    logger.info("RPC listening on %s:%s (clients: submit_transaction/health; nodes: block_confirmation)", RPC_LISTEN_HOST, RPC_LISTEN_PORT)

    def handle(conn, addr):
        try:
            conn.settimeout(15)
            msg = _recv_json(conn)
            if not msg:
                conn.close()
                return
            if msg.get('type') == 'block_confirmation':
                logger.info("=== TRANSACTION CONFIRMED (block committed) === block_index=%s block_hash=%s miner_id=%s node_id=%s timestamp=%s",
                            msg.get('block_index'), msg.get('block_hash'), msg.get('miner_id'), msg.get('node_id'), msg.get('timestamp'))
                logger.info("Saved to ledger: block_index=%s", msg.get('block_index'))
                notify_server(msg)
                conn.close()
                return
            action = msg.get('action')
            if action == 'health':
                _send_json(conn, {'status': 'ok', 'service': 'rpc_server'})
                conn.close()
                return
            if action == 'submit_transaction':
                body = msg.get('body') or msg
                if not body:
                    _send_json(conn, {'error': 'Invalid or missing body'})
                else:
                    from datetime import datetime
                    ts = datetime.utcnow().isoformat()
                    logger.info("=== TRANSACTION SUBMITTED === timestamp=%s sender=%s data=%s signature=%s",
                                ts, body.get('sender'), body.get('data'), body.get('signature'))
                    count, _ = make_transaction(body)
                    # Don't say "3/5 nodes" - say tx submitted and how many nodes got it
                    status_msg = "Transaction submitted. Broadcast to %s node(s). Pending confirmation." % count
                    if count == 0:
                        status_msg = "Transaction failed: no nodes reached. Start nodes first."
                    _send_json(conn, {
                        'status': 'submitted' if count else 'failed',
                        'nodes_reached': count,
                        'message': status_msg,
                        'timestamp': ts,
                        'transaction': {'sender': body.get('sender'), 'data': body.get('data')},
                    })
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
    logger.info("RPC server stopped")


if __name__ == '__main__':
    main()
