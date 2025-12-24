"""
Proof of Authority Manager
Handles PoA consensus rules and validation
"""

import json
import socket
import threading
import logging
from poa_node import PoANode
from config import *
from utils import (
    is_valid_block, is_valid_peer_address, send_to_peer,
    log_block_added, log_broadcast_result
)

logger = logging.getLogger(__name__)


class ManagerPoA:
    """Manages Proof of Authority consensus and peer communication"""
    
    # ========================================================================
    # INITIALIZATION
    # ========================================================================
    
    def __init__(self, node_id, port=POA_DEFAULT_PORT, authorized_nodes=None):
        """Initialize PoA Manager"""
        self.node_id = node_id
        self.port = port
        self.authorized_nodes = authorized_nodes or []
        self.node = PoANode(node_id, is_authority=(node_id in self.authorized_nodes))
        self.peers = []
        self.socket = None
        self.is_running = False
        logger.info(f"[{self.node_id}] PoA Manager initialized (port={port})")
    
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
    # SIGNATURE VALIDATION
    # ========================================================================
    
    def validate_signature(self, node_id, signature, data):
        """Validate signature from authorized node"""
        if not node_id or not signature:
            logger.error(f"[{self.node_id}] Missing signature data")
            return False
        
        # Check authorization
        if node_id not in self.authorized_nodes:
            logger.warning(f"[{self.node_id}] Unauthorized node: {node_id}")
            return False
        
        # Check signature format
        expected_prefix = f"{SIGNATURE_PREFIX}{node_id}"
        if not signature.startswith(expected_prefix):
            logger.warning(f"[{self.node_id}] Invalid signature format")
            return False
        
        logger.info(f"[{self.node_id}] Signature valid from {node_id}")
        return True
    
    # ========================================================================
    # BLOCK OPERATIONS
    # ========================================================================
    
    def broadcast_block(self, block):
        """Broadcast block to all peers"""
        if not block:
            logger.error(f"[{self.node_id}] {ERROR_EMPTY_BLOCK}")
            return
        
        try:
            message = {
                MSG_FIELD_TYPE: MSG_TYPE_BLOCK_COMMITTED,
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
        """Start the PoA Manager"""
        try:
            self.is_running = True
            logger.info(f"[{self.node_id}] Starting PoA Manager on port {self.port}")
            
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
            
            if msg_type == MSG_TYPE_NEW_TRANSACTION:
                self._handle_transaction(message)
            elif msg_type == MSG_TYPE_BLOCK_COMMITTED:
                self._handle_block_committed(message)
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
    
    def _handle_transaction(self, message):
        """Handle NEW_TRANSACTION message"""
        sender_id = message.get(MSG_FIELD_ID)
        signature = message.get(MSG_FIELD_SIG)
        block_data = message.get(MSG_FIELD_DATA)
        
        if not all([sender_id, signature, block_data]):
            logger.warning(f"[{self.node_id}] Incomplete transaction data")
            return
        
        if self.validate_signature(sender_id, signature, block_data):
            logger.info(f"[{self.node_id}] Authority verified from {sender_id}")
            block = self.node.create_block(block_data, sender_id, signature)
            if self.node.add_block(block):
                self.broadcast_block(block)
        else:
            logger.warning(f"[{self.node_id}] Invalid signature from {sender_id}")
    
    def _handle_block_committed(self, message):
        """Handle BLOCK_COMMITTED message"""
        block = message.get(MSG_FIELD_CONTENT)
        sender = message.get(MSG_FIELD_SENDER)
        
        if not block:
            logger.warning(f"[{self.node_id}] Empty block from {sender}")
            return
        
        if self.node.add_block(block):
            logger.info(f"[{self.node_id}] Block committed by {sender}")
    
    def stop(self):
        """Stop the PoA Manager"""
        try:
            self.is_running = False
            if self.socket:
                self.socket.close()
            logger.info(f"[{self.node_id}] PoA Manager stopped")
        except Exception as e:
            logger.error(f"[{self.node_id}] Error stopping: {e}", exc_info=True)
