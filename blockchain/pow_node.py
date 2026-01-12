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

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

try:
    from db_init import get_db_connection
except:
    print("⚠️ db_init not available, creating minimal version")
    def get_db_connection():
        import sqlite3
        return sqlite3.connect('database.sqlite3')

class PoWNode:
    """
    Proof of Work Node
    - Mines blocks using PoW
    - Discovers and connects to other nodes
    - Spreads information (gossip protocol)
    """
    
    def __init__(self, host='0.0.0.0', port=11111):
        """
        Initialize PoW Node (miner + validator)
        
        Args:
            host: Listening host (0.0.0.0 = all interfaces)
            port: Listening port (11111, 22222, 33333, 44444, 55555)
        """
        self.node_id = str(uuid.uuid4())  # Unique node identifier
        self.host = host
        self.port = port
        # Each node is both miner and validator
        self.is_running = False
        
        # P2P network
        self.known_nodes = {}  # node_id -> (host, port)
        self.connected_nodes = {}  # node_id -> socket
        
        # Blockchain
        self.current_block_hash = None
        self.difficulty = 4  # Number of leading zeros required
        self.mining = False
        self.validated_blocks = []  # Blocks validated by this node
        
        # Register this node in database
        self._register_node()
        
        print(f"🚀 PoW Node initialized (Miner + Validator)")
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
        
        print(f"👂 Listening for P2P connections on {self.host}:{self.port}")
        
        while self.is_running:
            try:
                client_socket, (client_host, client_port) = server_socket.accept()
                print(f"📥 New connection from {client_host}:{client_port}")
                
                # Handle connection in separate thread
                thread = threading.Thread(
                    target=self._handle_p2p_connection,
                    args=(client_socket, client_host, client_port)
                )
                thread.daemon = True
                thread.start()
            except Exception as e:
                if self.is_running:
                    print(f"❌ Error accepting connection: {e}")
        
        server_socket.close()
    
    def _handle_p2p_connection(self, client_socket, client_host, client_port):
        """Handle incoming P2P message"""
        try:
            data = client_socket.recv(4096)
            message = json.loads(data.decode())
            
            print(f"📬 Received message: {message.get('type', 'unknown')}")
            
            # Handle different message types
            msg_type = message.get('type')
            
            if msg_type == 'ping':
                self._send_pong(client_socket)
            elif msg_type == 'node_discovery':
                self._send_node_list(client_socket)
            elif msg_type == 'new_block':
                self._handle_new_block(message)
            elif msg_type == 'new_transaction':
                self._handle_new_transaction(message)
            
            client_socket.close()
        except Exception as e:
            print(f"❌ Error handling P2P connection: {e}")
    
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
    
    def _handle_new_transaction(self, message):
        """Handle incoming transaction"""
        tx_hash = message.get('tx_hash')
        print(f"💳 New transaction received: {tx_hash}")
    
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
                print(f"📤 Broadcast to {node_id}")
            except Exception as e:
                print(f"⚠️ Failed to reach {node_id}: {e}")
    
    def validate_block(self, block_hash, nonce):
        """
        Validate block by checking if hash meets difficulty requirement
        """
        if not block_hash or not isinstance(block_hash, str):
            return False
        
        # Check if hash starts with required leading zeros
        difficulty_target = '0' * self.difficulty
        is_valid = block_hash.startswith(difficulty_target)
        
        if is_valid:
            print(f"✅ Block hash valid: {block_hash[:16]}...")
        else:
            print(f"❌ Block hash invalid (not enough leading zeros): {block_hash[:16]}...")
        
        return is_valid
    
    def mine_block(self, transactions_data=""):
        """
        Mine a block using Proof of Work
        Find nonce such that hash starts with required zeros
        """
        self.mining = True
        nonce = 0
        start_time = time.time()
        
        print(f"⛏️ Mining block (difficulty: {self.difficulty})...")
        
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
            if block_hash.startswith('0' * self.difficulty):
                elapsed = time.time() - start_time
                print(f"✅ Block mined!")
                print(f"   Hash: {block_hash}")
                print(f"   Nonce: {nonce}")
                print(f"   Time: {elapsed:.2f}s")
                
                self.current_block_hash = block_hash
                self.broadcast_message('new_block', {
                    'block_hash': block_hash,
                    'nonce': nonce,
                    'data': transactions_data
                })
                self.mining = False
                return block_hash
            
            nonce += 1
            
            # Progress indicator
            if nonce % 10000 == 0:
                print(f"   Trying nonce: {nonce}")
        
        return None
    
    def stop(self):
        """Stop the node"""
        self.is_running = False
        self.mining = False
        print(f"🛑 Node stopping...")
    
    def _mine_puzzle(self, data):
        """Internal mining loop"""
        nonce = MIN_NONCE
        start_time = time.time()
        
        while self.is_mining:
            hash_value = self._compute_hash(data, nonce)
            
            if check_hash_difficulty(hash_value, self.difficulty):
                elapsed_time = time.time() - start_time
                log_block_solution(self.node_id, hash_value, nonce, elapsed_time)
                return hash_value, nonce
            
            nonce += 1
            
            if nonce % MINING_PROGRESS_INTERVAL == 0:
                log_mining_progress(self.node_id, nonce)
        
        return None, None
    
    def _compute_hash(self, data, nonce):
        """Compute SHA256 hash"""
        target = create_hash_target(data, nonce)
        return hashlib.sha256(target).hexdigest()
    
    # ========================================================================
    # BLOCK MANAGEMENT
    # ========================================================================
    
    def create_block(self, data, previous_hash=None, nonce=0, hash_value=None):
        """Create a new PoW block"""
        block = {
            BLOCK_FIELD_INDEX: len(self.chain),
            BLOCK_FIELD_TIMESTAMP: time.time(),
            BLOCK_FIELD_DATA: data,
            BLOCK_FIELD_PREVIOUS_HASH: previous_hash,
            BLOCK_FIELD_NONCE: nonce,
            BLOCK_FIELD_HASH: hash_value,
        }
        logger.debug(f"[{self.node_id}] Block created")
        return block
    
    def add_block(self, block):
        """Add block to chain"""
        is_valid, missing_fields = is_valid_block(block, [BLOCK_FIELD_HASH, BLOCK_FIELD_NONCE])
        if not is_valid:
            logger.error(f"[{self.node_id}] {ERROR_INVALID_BLOCK}")
            return False
        
        try:
            self.chain.append(block)
            log_block_added(self.node_id, len(self.chain))
            return True
        except Exception as e:
            logger.error(f"[{self.node_id}] Error adding block: {e}", exc_info=True)
            return False
    
    # ========================================================================
    # CHAIN OPERATIONS
    # ========================================================================
    
    def get_chain_length(self):
        """Get chain length"""
        return len(self.chain)
    
    def get_last_block(self):
        """Get last block"""
        return self.chain[-1] if self.chain else None
    
    def get_chain_copy(self):
        """Get copy of blockchain"""
        return self.chain.copy()
