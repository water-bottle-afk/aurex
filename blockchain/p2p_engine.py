"""
P2P Blockchain Engine
Universal engine that can run in PoW or PoA mode
Each instance is independent and acts as both Server and Client (Servent)
"""

import json
import socket
import threading
import time
import logging
from manager_pow import ManagerPoW
from manager_poa import ManagerPoA
from config import *
from utils import create_transaction_message, send_to_peer

logger = logging.getLogger(__name__)


class P2PEngine:
    """Independent P2P Blockchain Node"""
    
    # ========================================================================
    # INITIALIZATION
    # ========================================================================
    
    def __init__(self, node_id, my_ip="127.0.0.1", port=None, mode=POW_MODE,
                 difficulty=DEFAULT_POW_DIFFICULTY, authorized_nodes=None):
        """
        Initialize P2P Engine
        
        Args:
            node_id: Unique node identifier
            my_ip: Node IP address
            port: Listen port
            mode: "POW" or "POA"
            difficulty: PoW difficulty level
            authorized_nodes: List of authorized PoA nodes
        """
        self.node_id = node_id
        self.my_ip = my_ip
        self.mode = mode
        self.is_running = False
        self.peers = []
        
        # Set default port based on mode
        if port is None:
            port = POW_DEFAULT_PORT if mode == POW_MODE else POA_DEFAULT_PORT
        self.port = port
        
        # Initialize manager based on mode
        if mode == POW_MODE:
            self.manager = ManagerPoW(node_id, port=port, difficulty=difficulty)
        elif mode == POA_MODE:
            self.manager = ManagerPoA(node_id, port=port, authorized_nodes=authorized_nodes)
        else:
            raise ValueError(f"{ERROR_INVALID_MODE}: {mode}")
        
        logger.info(f"[{self.node_id}] P2P Engine initialized ({mode} mode)")
    
    # ========================================================================
    # PEER MANAGEMENT
    # ========================================================================
    
    def add_peer(self, ip, port):
        """Add a peer to the network"""
        if self.manager.add_peer(ip, port):
            self.peers.append((ip, port))
            return True
        return False
    
    def get_peer_count(self):
        """Get number of connected peers"""
        return len(self.peers)
    
    # ========================================================================
    # ENGINE OPERATIONS
    # ========================================================================
    
    def start(self):
        """Start the P2P Engine"""
        try:
            self.is_running = True
            self._log_startup_info()
            self.manager.start()
        except Exception as e:
            logger.error(f"[{self.node_id}] Error starting engine: {e}", exc_info=True)
            self.is_running = False
    
    def _log_startup_info(self):
        """Log engine startup information"""
        logger.info("=" * 60)
        logger.info(f"P2P Blockchain Engine Started")
        logger.info(f"Node ID: {self.node_id}")
        logger.info(f"Mode: {self.mode}")
        logger.info(f"Address: {self.my_ip}:{self.port}")
        logger.info(f"Status: RUNNING")
        logger.info("=" * 60)
    
    def stop(self):
        """Stop the P2P Engine"""
        try:
            self.is_running = False
            self.manager.stop()
            logger.info(f"[{self.node_id}] P2P Engine stopped")
        except Exception as e:
            logger.error(f"[{self.node_id}] Error stopping: {e}", exc_info=True)
    
    # ========================================================================
    # TRANSACTION OPERATIONS
    # ========================================================================
    
    def send_transaction(self, data, target_ip=None, target_port=None):
        """
        Send transaction to network
        
        Args:
            data: Transaction data
            target_ip: Specific peer IP (None = broadcast to all)
            target_port: Specific peer port
            
        Returns:
            bool: Success status
        """
        if not data:
            logger.error(f"[{self.node_id}] {ERROR_EMPTY_TRANSACTION}")
            return False
        
        try:
            # Create transaction message
            node_sig = None
            if self.mode == POA_MODE and self.manager.node.is_authority:
                node_sig = self.manager.node.sign_data(data)
            
            message = create_transaction_message(data, self.node_id, node_sig)
            
            if target_ip and target_port:
                return self._send_to_specific_peer(message, target_ip, target_port)
            else:
                return self._broadcast_transaction(message)
        except Exception as e:
            logger.error(f"[{self.node_id}] Error sending transaction: {e}", exc_info=True)
            return False
    
    def _send_to_specific_peer(self, message, ip, port):
        """Send message to specific peer"""
        success, error = send_to_peer(ip, port, message)
        if success:
            logger.info(f"[{self.node_id}] Sent to {ip}:{port}")
        else:
            logger.warning(f"[{self.node_id}] Send failed: {error}")
        return success
    
    def _broadcast_transaction(self, message):
        """Broadcast transaction to all peers"""
        if not self.peers:
            logger.warning(f"[{self.node_id}] No peers to broadcast to")
            return False
        
        success_count = 0
        for ip, port in self.peers:
            success, _ = send_to_peer(ip, port, message)
            if success:
                success_count += 1
        
        logger.info(f"[{self.node_id}] Broadcast to {success_count}/{len(self.peers)} peers")
        return success_count > 0
    
    # ========================================================================
    # STATUS OPERATIONS
    # ========================================================================
    
    def get_status(self):
        """Get engine status"""
        return {
            'node_id': self.node_id,
            'mode': self.mode,
            'is_running': self.is_running,
            'address': f"{self.my_ip}:{self.port}",
            'peers': len(self.peers),
            'chain_length': len(self.manager.node.chain),
            'pending': len(self.manager.node.pending_blocks)
            if hasattr(self.manager.node, 'pending_blocks') else 0
        }
    
    def print_status(self):
        """Print engine status"""
        status = self.get_status()
        logger.info(f"\n[Status] Node {status['node_id']}:")
        logger.info(f"  Mode: {status['mode']}")
        logger.info(f"  Address: {status['address']}")
        logger.info(f"  Running: {status['is_running']}")
        logger.info(f"  Peers: {status['peers']}")
        logger.info(f"  Chain Length: {status['chain_length']}")
        if status['pending']:
            logger.info(f"  Pending: {status['pending']}")
    
    def print_chain(self):
        """Print blockchain"""
        chain = self.manager.node.chain
        logger.info(f"\n[Blockchain] Node {self.node_id} - {len(chain)} blocks:")
        for i, block in enumerate(chain):
            logger.info(f"  Block {i}: {json.dumps(block, indent=2)}")


if __name__ == "__main__":
    # Example usage
    engine_pow = P2PEngine("Node_PoW_1", mode=POW_MODE, difficulty=2)
    engine_pow.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        engine_pow.stop()
