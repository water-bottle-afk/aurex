"""
PoW Node Class - Proof of Work blockchain node with P2P networking
Implements node discovery, mining, and gossip protocol
"""

import socket
import json
import hashlib
import time
import uuid
import threading
from datetime import datetime
import sys
import os
import logging

logger = logging.getLogger(__name__)

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from json_ledger import get_ledger

try:
    from db_init import get_db_connection
except:
    print("⚠️ db_init not available")

from key_manager import NodeKeyManager


class PoWNode:
    """
    Proof of Work Node
    - Mines blocks using PoW
    - Discovers and connects to other nodes
    - Spreads information (gossip protocol)
    """
    
    def __init__(self, host='0.0.0.0', port=11111, difficulty=2):
        """
        Initialize PoW Node (miner + validator)
        
        Args:
            host: Listening host (0.0.0.0 = all interfaces)
            port: Listening port (11111, 22222, 33333, 44444, 55555)
            difficulty: Number of leading zeros required in hash
        """
        self.node_id = str(uuid.uuid4())  # Unique node identifier
        self.host = host
        self.port = port
        # Each node is both miner and validator
        self.is_running = False
        
        # Digital signatures - each node has its own key pair
        self.key_manager = NodeKeyManager(self.node_id)
        
        # P2P network
        self.known_nodes = {}  # node_id -> (host, port)
        self.connected_nodes = {}  # node_id -> socket
        
        # Blockchain
        self.current_block_hash = None
        self.difficulty = difficulty  # Number of leading zeros required
        self.mining = False
        self.validated_blocks = []  # Blocks validated by this node
        
        # Register this node in database
        self._register_node()
        
        print(f"🚀 PoW Node initialized (Miner + Validator)")
        print(f"   🔑 Digital Signatures: ENABLED")
        print(f"   Node ID: {self.node_id}")
        print(f"   Listening: {self.host}:{self.port}")
    
    def _register_node(self):
        """Register this node in the database"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('''
                INSERT OR REPLACE INTO nodes (node_id, host, port, node_type, status)
                VALUES (?, ?, ?, ?, 'active')
            ''', (self.node_id, self.host, self.port, 'full-node'))
            
            conn.commit()
            conn.close()
            print(f"✅ Node registered in database")
        except Exception as e:
            print(f"⚠️ Could not register node: {e}")
    
    def discover_nodes(self):
        """
        Discover known nodes from database
        This implements gossip protocol - get list of nearby nodes
        """
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute('SELECT node_id, host, port FROM nodes WHERE status = "active" AND node_id != ?', (self.node_id,))
            nodes = cursor.fetchall()
            
            for node in nodes:
                node_id, host, port = node
                self.known_nodes[node_id] = (host, port)
                print(f"📍 Discovered node: {node_id} at {host}:{port}")
            
            conn.close()
            print(f"✅ Found {len(self.known_nodes)} known nodes")
        except Exception as e:
            print(f"⚠️ Could not discover nodes: {e}")
    
    def start_listening(self):
        """Start listening for incoming P2P connections"""
        self.is_running = True
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(5)
        
        print(f"👂 Listening on {self.host}:{self.port}")
        
        while self.is_running:
            try:
                client_socket, (client_host, client_port) = server_socket.accept()
                
                # Handle connection in separate thread
                thread = threading.Thread(
                    target=self._handle_p2p_connection,
                    args=(client_socket, client_host, client_port)
                )
                thread.daemon = True
                thread.start()
            except Exception as e:
                if self.is_running:
                    pass
        
        server_socket.close()
    
    def _handle_p2p_connection(self, client_socket, client_host, client_port):
        """Handle incoming P2P message"""
        try:
            data = client_socket.recv(4096)
            message = json.loads(data.decode())
            
            msg_type = message.get('type')
            
            if msg_type == 'ping':
                self._send_pong(client_socket)
                client_socket.close()
            elif msg_type == 'node_discovery':
                self._send_node_list(client_socket)
                client_socket.close()
            elif msg_type == 'new_block':
                self._handle_new_block(message)
                client_socket.close()
            elif msg_type == 'NEW_TRANSACTION':
                # Keep socket open and mine the transaction
                self._handle_new_transaction(message, client_socket)
            else:
                client_socket.close()
        except Exception as e:
            try:
                client_socket.close()
            except:
                pass
    
    def _send_pong(self, socket):
        """Respond to ping"""
        response = {
            'type': 'pong',
            'node_id': self.node_id,
            'timestamp': datetime.now().isoformat()
        }
        socket.send(json.dumps(response).encode())
    
    def _send_node_list(self, socket):
        """Send list of known nodes (gossip protocol)"""
        response = {
            'type': 'node_list',
            'node_id': self.node_id,
            'nodes': [
                {'node_id': nid, 'host': host, 'port': port}
                for nid, (host, port) in self.known_nodes.items()
            ]
        }
        socket.send(json.dumps(response).encode())
    
    def _handle_new_block(self, message):
        """Handle incoming block from another node"""
        block_hash = message.get('block_hash')
        block_nonce = message.get('nonce')
        block_data = message.get('data')
        
        print(f"📦 New block received: {block_hash}")
        
        # Validate block
        if self.validate_block(block_hash, block_nonce):
            self.validated_blocks.append(block_hash)
            print(f"✅ Block validated: {block_hash}")
            # Broadcast to other nodes that we validated this
            self.broadcast_message('block_validated', {
                'block_hash': block_hash,
                'validator': self.node_id
            })
        else:
            print(f"❌ Block validation failed: {block_hash}")
    
    def _handle_new_transaction(self, message, client_socket):
        """Handle incoming transaction and start mining in background thread"""
        try:
            tx_data = message.get('data', {})
            asset_name = tx_data.get('asset', 'unknown')
            
            # Extract confirmation details from app server
            confirmation_host = message.get('confirmation_host', '127.0.0.1')
            confirmation_port = message.get('confirmation_port', 13290)
            
            # Send immediate acknowledgment to client
            ack_response = {
                'type': 'MINING_STARTED',
                'miner': self.node_id,
                'message': 'Mining started'
            }
            client_socket.send(json.dumps(ack_response).encode())
            
            # Close client socket
            client_socket.close()
            
            # Create block data from transaction
            block_data = json.dumps(tx_data)
            
            # Start mining in background thread
            mining_thread = threading.Thread(
                target=self._mine_and_broadcast,
                args=(block_data, asset_name, confirmation_host, confirmation_port),
                daemon=True
            )
            mining_thread.start()
            
        except Exception as e:
            try:
                error_response = {
                    'type': 'ERROR',
                    'error': str(e),
                    'miner': self.node_id
                }
                client_socket.send(json.dumps(error_response).encode())
            except:
                pass
            finally:
                try:
                    client_socket.close()
                except:
                    pass
    
    def _mine_and_broadcast(self, block_data, asset_name, confirmation_host='127.0.0.1', confirmation_port=13290):
        """Mine block in background and send confirmation to app server"""
        try:
            # Mine the block (broadcasts automatically inside mine_block)
            block_hash, nonce = self.mine_block(block_data)
            
            if block_hash:
                # Send block confirmation to app server
                confirmation = {
                    'type': 'block_confirmation',
                    'miner_node_id': self.node_id,
                    'block_hash': block_hash,
                    'asset': asset_name,
                    'timestamp': datetime.now().isoformat()
                }
                
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(5)
                    sock.connect((confirmation_host, confirmation_port))
                    sock.send(json.dumps(confirmation).encode())
                    sock.close()
                    print(f"📢 Block confirmation sent to app server")
                except Exception as e:
                    print(f"⚠️ Could not send confirmation: {e}")
            
        except Exception as e:
            print(f"❌ Error in mining: {e}")
    
    def broadcast_message(self, message_type, data):
        """Broadcast message to all known nodes"""
        message = {
            'type': message_type,
            'node_id': self.node_id,
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        
        for node_id, (host, port) in self.known_nodes.items():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.connect((host, port))
                sock.send(json.dumps(message).encode())
                sock.close()
            except Exception as e:
                pass
    
    def validate_block(self, block_hash, nonce):
        """
        Validate block by checking if hash meets difficulty requirement
        
        DEBUG OUTPUT:
        - Block hash (first 16 chars)
        - Nonce value
        - Difficulty requirement
        - Validation result
        """
        if not block_hash or not isinstance(block_hash, str):
            print(f"❌ [{self.node_id}] Invalid block hash type: {type(block_hash)}")
            return False
        
        # Check if hash starts with required leading zeros
        difficulty_target = '0' * self.difficulty
        is_valid = block_hash.startswith(difficulty_target)
        
        if is_valid:
            print(f"\n✅ [{self.node_id}] BLOCK VALIDATED")
            print(f"   Hash: {block_hash}")
            print(f"   Nonce: {nonce}")
            print(f"   Difficulty: {self.difficulty} zeros ✓\n")
            
            # Store validation in database
            self._store_validation_in_db(block_hash, nonce)
        else:
            print(f"\n❌ [{self.node_id}] BLOCK INVALID")
            print(f"   Hash: {block_hash[:16]}...")
            print(f"   Expected: {difficulty_target}...")
            print(f"   Got: {block_hash[:self.difficulty]}...")
            print(f"   Nonce: {nonce}\n")
        
        return is_valid
    
    def _store_validation_in_db(self, block_hash, nonce):
        """Store block validation in database"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if block exists
            cursor.execute('SELECT id FROM blocks WHERE block_hash = ?', (block_hash,))
            result = cursor.fetchone()
            
            if result:
                print(f"   [DB] Block already in ledger: {block_hash[:16]}...")
            else:
                print(f"   [DB] New valid block: {block_hash[:16]}...")
            
            conn.close()
        except Exception as e:
            print(f"   ⚠️ Database error during validation: {e}")
    
    def mine_block(self, transactions_data=""):
        """
        Mine a block using Proof of Work
        Find nonce such that hash starts with required zeros
        """
        self.mining = True
        nonce = 0
        start_time = time.time()
        target_zeros = '0' * self.difficulty
        
        print(f"⛏️ Mining block (difficulty: {self.difficulty})")
        
        while self.mining:
            # Create block data
            block_data = {
                'previous_hash': self.current_block_hash or '0' * 64,
                'nonce': nonce,
                'timestamp': datetime.now().isoformat(),
                'miner': self.node_id,
                'data': transactions_data
            }
            
            # Calculate hash
            block_str = json.dumps(block_data, sort_keys=True)
            block_hash = hashlib.sha256(block_str.encode()).hexdigest()
            
            # Check if hash meets difficulty requirement
            if block_hash.startswith(target_zeros):
                elapsed = time.time() - start_time
                
                print(f"✅ BLOCK FOUND!")
                print(f"   Hash: {block_hash}")
                print(f"   Time: {elapsed:.2f}s | Attempts: {nonce}\n")
                
                self.current_block_hash = block_hash
                
                # Store block in database
                self._store_block_in_db(block_hash, nonce, transactions_data)
                
                # Broadcast to peers
                self.broadcast_message('new_block', {
                    'block_hash': block_hash,
                    'nonce': nonce,
                    'data': transactions_data,
                    'miner': self.node_id
                })
                
                self.mining = False
                return block_hash, nonce
            
            nonce += 1
        
        return None, None
    
    def _store_block_in_db(self, block_hash, nonce, data):
        """Store mined block in JSON ledger with digital signature"""
        try:
            ledger = get_ledger()
            previous_hash = self.current_block_hash or '0' * 64
            
            # Sign the block with this node's private key
            block_signature = self.key_manager.sign_data(block_hash)
            public_key_pem = self.key_manager.get_public_key_pem()
            
            # Add block with signature
            block = ledger.add_block(
                block_hash=block_hash,
                nonce=nonce,
                miner_id=self.node_id,
                difficulty=self.difficulty,
                data=data,
                previous_hash=previous_hash,
                signature=block_signature,
                public_key=public_key_pem
            )
            
            print(f"   💾 Block saved to ledger: {block_hash[:16]}...")
            print(f"   ✍️  Signed with node's private key\n")
        except Exception as e:
            print(f"   ⚠️ Ledger error: {e}\n")
    
    def stop(self):
        """Stop the node"""
        self.is_running = False
        self.mining = False
        print(f"🛑 Node stopping...")
    
    
    # ========================================================================
    # BLOCK MANAGEMENT
    # ========================================================================
    
