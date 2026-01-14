"""
Simple PoW Node Class - No script generation needed!
Just instantiate and run in a thread
"""

import threading
import time
from pow_node import PoWNode
from db_init import init_database


class BlockchainNode:
    """Wrapper around PoWNode that runs in a thread"""
    
    def __init__(self, node_name, host, port, difficulty):
        """Initialize a blockchain node"""
        self.node_name = node_name
        self.host = host
        self.port = port
        self.difficulty = difficulty
        self.node = None
        self.thread = None
        self.running = False
    
    def start(self):
        """Start the node in a background thread"""
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=False)
        self.thread.start()
        print(f"✅ {self.node_name} started (listening on {self.port})")
    
    def _run(self):
        """Run the node"""
        try:
            print(f"\n🚀 [{self.node_name}] Starting on port {self.port}...")
            
            # Initialize database
            init_database()
            
            # Create PoW node
            self.node = PoWNode(host=self.host, port=self.port, difficulty=self.difficulty)
            
            # Discover peers
            self.node.discover_nodes()
            
            # Start listening
            print(f"✅ [{self.node_name}] Ready - listening on port {self.port}\n")
            
            # This blocks until node is stopped
            self.node.start_listening()
        
        except Exception as e:
            print(f"\n❌ [{self.node_name}] ERROR: {e}")
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
        print(f"⛔ {self.node_name} stopped")
