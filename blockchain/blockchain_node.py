"""
Simple PoW Node Class - No script generation needed!
Just instantiate and run in a thread
"""

import threading
import time
import json
import socket
import struct
from pow_node import PoWNode
from db_init import init_database


class BlockchainNode:
    """Wrapper around PoWNode that runs in a thread"""
    
    def __init__(self, node_name, host, port, difficulty, gateway_host=None, gateway_port=None):
        """Initialize a blockchain node"""
        self.node_name = node_name
        self.host = host
        self.port = port
        self.difficulty = difficulty
        self.gateway_host = gateway_host
        self.gateway_port = gateway_port
        self.node = None
        self.thread = None
        self.running = False
    
    def start(self):
        """Start the node in a background thread"""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=False)
        self.thread.start()
        print(f" {self.node_name} started (listening on {self.port})")
    
    def _run(self):
        """Run the node"""
        try:
            print(f"\n [{self.node_name}] Starting on port {self.port}...")
            
            # Initialize database
            init_database()
            
            # Create PoW node
            self.node = PoWNode(
                host=self.host,
                port=self.port,
                difficulty=self.difficulty,
                gateway_host=self.gateway_host,
                gateway_port=self.gateway_port,
            )
            
            # Discover peers
            self.node.discover_nodes()
            
            # Start listening
            print(f" [{self.node_name}] Ready - listening on port {self.port}\n")
            
            # This blocks until node is stopped
            self.node.start_listening()
        
        except Exception as e:
            print(f"\n [{self.node_name}] ERROR: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            self.running = False
    
    def stop(self):
        """Stop the node"""
        if self.node:
            self.node.is_running = False
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        print(f" {self.node_name} stopped")

    # ── Direct gateway submission helpers ─────────────────────────────────

    def _send_to_gateway(self, payload, timeout=10):
        """
        Send a length-prefixed JSON message to the gateway and return the response.
        Uses the same 2-byte big-endian prefix as the rest of the protocol.
        """
        gw_host = self.gateway_host or '127.0.0.1'
        gw_port = int(self.gateway_port or 5000)
        raw = json.dumps(payload).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            sock.connect((gw_host, gw_port))
            sock.send(struct.pack('>H', len(raw)) + raw)
            # read response
            len_buf = sock.recv(2)
            if len(len_buf) < 2:
                return None
            (size,) = struct.unpack('>H', len_buf)
            data = b''
            while len(data) < size:
                chunk = sock.recv(min(size - len(data), 4096))
                if not chunk:
                    break
                data += chunk
            return json.loads(data.decode())
        except Exception as e:
            print(f" [{self.node_name}] gateway send error: {e}")
            return None
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def submit_mint(
        self,
        tx_id,
        asset_hash,
        asset_name,
        initial_owner,
        initial_owner_pk,
        metadata_link,
        timestamp,
        signature,
    ):
        """
        Submit a MINT transaction to the gateway.

        Block data fields (per spec):
            tx_type   : MINT
            asset_hash       : SHA-256 of the uploaded file
            initial_owner_pk : base64-encoded Ed25519 public key of the uploader
            metadata_link    : relative path stored in marketplace DB  (e.g. alice/photo.jpg)
        """
        tx_data = {
            'action': 'asset_mint',
            'tx_id': tx_id,
            'asset_hash': asset_hash,
            'asset_name': asset_name,
            'owner': initial_owner,
            'owner_pub': initial_owner_pk,
            'metadata_link': metadata_link,
            'timestamp': timestamp,
        }
        payload = {
            'action': 'submit_transaction',
            'body': {
                'sender': initial_owner,
                'data': tx_data,
                'signature': signature,
                'public_key': initial_owner_pk,
            },
        }
        return self._send_to_gateway(payload)

    def submit_transfer(
        self,
        tx_id,
        asset_hash,
        asset_name,
        asset_id,
        sender,
        sender_pk,
        receiver,
        receiver_pk,
        price,
        timestamp,
        signature,
    ):
        """
        Submit a TRANSFER transaction to the gateway.

        Block data fields (per spec):
            tx_type   : TRANSFER
            asset_hash  : SHA-256 of the asset file
            sender_pk   : base64 Ed25519 public key of the sender
            receiver_pk : base64 Ed25519 public key of the receiver
            price       : sale price
        """
        tx_data = {
            'action': 'asset_transfer',
            'tx_id': tx_id,
            'asset_hash': asset_hash,
            'asset_name': asset_name,
            'asset_id': asset_id,
            'from': sender,
            'to': receiver,
            'sender_pk': sender_pk,
            'receiver_pk': receiver_pk,
            'amount': price,
            'price': price,
            'timestamp': timestamp,
        }
        payload = {
            'action': 'submit_transaction',
            'body': {
                'sender': sender,
                'data': tx_data,
                'signature': signature,
                'public_key': sender_pk,
            },
        }
        return self._send_to_gateway(payload)
