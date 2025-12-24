"""
Proof of Work Manager
Handles PoW consensus rules and broadcasting
"""

import json
import socket
import threading
import logging
from pow_node import PoWNode
from config import *
from utils import (
    is_valid_block, is_valid_peer_address, send_to_peer,
    log_block_added, log_broadcast_result
)

logger = logging.getLogger(__name__)


class ManagerPoW:
    """Manages Proof of Work consensus and peer communication"""
    
    # ========================================================================
    # INITIALIZATION
    # ========================================================================
    
    def __init__(self, node_id, port=POW_DEFAULT_PORT, difficulty=DEFAULT_POW_DIFFICULTY):
        """Initialize PoW Manager"""
        self.node_id = node_id
        self.port = port
        self.peers = []
        self.node = PoWNode(node_id, difficulty=difficulty)
        self.socket = None
        self.is_running = False
        logger.info(f"[{self.node_id}] PoW Manager initialized (port={port})")
    
    # ========================================================================
    # PEER MANAGEMENT
    # ========================================================================
    
    def add_peer(self, ip, port):
        """Add a peer node"""
        if not is_valid_peer_address(ip, port):
            logger.error(f"[{self.node_id}] {ERROR_INVALID_PEER}")
            return False
        
        self.peers.append((ip, port))
        logger.info(f"[{self.node_id}] Added peer: {ip}:{port}")
        return True
    
    # ========================================================================
    # BLOCK OPERATIONS
    # ========================================================================
    
    def validate_block(self, block):
        """Validate received PoW block"""
        is_valid, missing = is_valid_block(block, [BLOCK_FIELD_HASH, BLOCK_FIELD_NONCE])
        if not is_valid:
            logger.error(f"[{self.node_id}] {ERROR_INVALID_BLOCK} (missing: {missing})")
            return False
        
        try:
            hash_value = block.get(BLOCK_FIELD_HASH)
            if not hash_value:
                logger.error(f"[{self.node_id}] {BLOCK_FIELD_HASH} field missing")
                return False
            
            # Check difficulty
            required_prefix = '0' * self.node.difficulty
            if hash_value.startswith(required_prefix):
                logger.info(f"[{self.node_id}] Block validation passed")
                return True
            else:
                logger.warning(f"[{self.node_id}] Block failed difficulty check")
                return False
        except Exception as e:
            logger.error(f"[{self.node_id}] Error validating block: {e}", exc_info=True)
            return False
    
    def broadcast_block(self, block):
        """Broadcast block to all peers"""
        if not block:
            logger.error(f"[{self.node_id}] {ERROR_EMPTY_BLOCK}")
            return
        
        try:
            message = {
                MSG_FIELD_TYPE: MSG_TYPE_BLOCK_FOUND,
                MSG_FIELD_CONTENT: block,
                MSG_FIELD_SENDER: self.node_id
            }
            
            success_count = 0
            for ip, port in self.peers:
                success, _ = send_to_peer(ip, port, message)
                if success:
                    success_count += 1
            
            log_broadcast_result(self.node_id, success_count, len(self.peers))
        except Exception as e:
            logger.error(f"[{self.node_id}] Error broadcasting: {e}", exc_info=True)
    
    # ========================================================================
    # NETWORK OPERATIONS
    # ========================================================================
    
    def start(self):
        """Start the PoW Manager"""
        try:
            self.is_running = True
            logger.info(f"[{self.node_id}] Starting PoW Manager on port {self.port}")
            
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.socket.bind(("0.0.0.0", self.port))
            self.socket.listen(DEFAULT_LISTEN_BACKLOG)
            logger.info(f"[{self.node_id}] Listening on port {self.port}")
            
            threading.Thread(target=self._accept_connections, daemon=True).start()
        except Exception as e:
            logger.error(f"[{self.node_id}] Error starting manager: {e}", exc_info=True)
            self.is_running = False
    
    def _accept_connections(self):
        """Accept incoming peer connections"""
        while self.is_running:
            try:
                client, addr = self.socket.accept()
                threading.Thread(
                    target=self._handle_message,
                    args=(client, addr),
                    daemon=True
                ).start()
            except socket.error as e:
                if self.is_running:
                    logger.warning(f"[{self.node_id}] Socket error: {e}")
            except Exception as e:
                if self.is_running:
                    logger.error(f"[{self.node_id}] Accept error: {e}", exc_info=True)
    
    def _handle_message(self, client, addr):
        """Handle incoming message from peer"""
        try:
            data = client.recv(SOCKET_BUFFER_SIZE).decode()
            if not data:
                return
            
            message = json.loads(data)
            msg_type = message.get(MSG_FIELD_TYPE)
            
            if msg_type == MSG_TYPE_BLOCK_FOUND:
                self._handle_block_found(message)
            elif msg_type == MSG_TYPE_NEW_TRANSACTION:
                self._handle_transaction(message)
            else:
                logger.warning(f"[{self.node_id}] Unknown message type: {msg_type}")
            
            client.close()
        except json.JSONDecodeError as e:
            logger.error(f"[{self.node_id}] JSON error from {addr}: {e}")
            client.close()
        except Exception as e:
            logger.error(f"[{self.node_id}] Message handler error: {e}", exc_info=True)
            try:
                client.close()
            except:
                pass
    
    def _handle_block_found(self, message):
        """Handle BLOCK_FOUND message"""
        block = message.get(MSG_FIELD_CONTENT)
        if not block:
            logger.warning(f"[{self.node_id}] Empty block in message")
            return
        
        if self.validate_block(block):
            if self.node.add_block(block):
                self.broadcast_block(block)
            else:
                logger.warning(f"[{self.node_id}] Failed to add validated block")
    
    def _handle_transaction(self, message):
        """Handle NEW_TRANSACTION message"""
        tx_data = message.get(MSG_FIELD_DATA)
        if not tx_data:
            logger.warning(f"[{self.node_id}] Empty transaction")
            return
        
        logger.info(f"[{self.node_id}] Mining transaction: {tx_data[:30]}...")
        self.node.is_mining = True
        hash_result, nonce = self.node.solve(tx_data)
        self.node.is_mining = False
        
        if hash_result:
            block = {
                BLOCK_FIELD_HASH: hash_result,
                BLOCK_FIELD_NONCE: nonce,
                BLOCK_FIELD_DATA: tx_data,
                BLOCK_FIELD_MINER: self.node_id,
                BLOCK_FIELD_TIMESTAMP: __import__('time').time(),
            }
            if self.node.add_block(block):
                self.broadcast_block(block)
            else:
                logger.error(f"[{self.node_id}] Failed to add mined block")
    
    def stop(self):
        """Stop the PoW Manager"""
        try:
            self.is_running = False
            self.node.is_mining = False
            if self.socket:
                self.socket.close()
            logger.info(f"[{self.node_id}] PoW Manager stopped")
        except Exception as e:
            logger.error(f"[{self.node_id}] Error stopping: {e}", exc_info=True)
