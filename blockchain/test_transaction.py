"""
Submit one example transaction to the RPC server (socket).
Run this AFTER starting the RPC server and at least one node.
"""

import socket
import struct
import json
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from config import RPC_HOST, RPC_LISTEN_PORT

# Example transaction: alice sends bob 10 coins (wallets in marketplace.db)
EXAMPLE_TRANSACTION = {
    "sender": "alice",
    "data": {
        "action": "transfer",
        "from": "alice",
        "to": "bob",
        "amount": 10,
        "note": "Payment for item #42",
    },
    "signature": "SIG_alice_abc123def456",
}

def send_json(sock, obj):
    raw = json.dumps(obj).encode()
    sock.send(struct.pack(">H", len(raw)) + raw)

def recv_json(sock, max_size=65536):
    len_buf = sock.recv(2)
    if len(len_buf) < 2:
        return None
    size, = struct.unpack(">H", len_buf)
    if size > max_size:
        return None
    data = b""
    while len(data) < size:
        chunk = sock.recv(min(size - len(data), 4096))
        if not chunk:
            return None
        data += chunk
    return json.loads(data.decode())

def main():
    print("=" * 60)
    print("Example transaction (sending to RPC)")
    print("=" * 60)
    print("Transaction:", json.dumps(EXAMPLE_TRANSACTION, indent=2))
    print()

    msg = {
        "action": "submit_transaction",
        "body": EXAMPLE_TRANSACTION,
    }

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((RPC_HOST, RPC_LISTEN_PORT))
        send_json(sock, msg)
        response = recv_json(sock)
        sock.close()

        if response:
            print("RPC response:", json.dumps(response, indent=2))
            if response.get("status") == "submitted":
                print()
                print("OK:", response.get("message"))
                print("Watch the RPC and node windows for mining and block confirmation.")
                print("When a block is confirmed, server will update wallets (alice -10, bob +10).")
            elif response.get("status") == "failed":
                print()
                print("Failed:", response.get("message"))
        else:
            print("No response from RPC.")
    except ConnectionRefusedError:
        print("ERROR: Could not connect to RPC. Is rpc_server.py running on", RPC_HOST + ":" + str(RPC_LISTEN_PORT), "?")
        sys.exit(1)
    except Exception as e:
        print("ERROR:", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
