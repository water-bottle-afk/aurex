"""
Blockchain Network Runner
Start multiple independent P2P nodes and manage the network
"""

import time
import threading
from p2p_engine import P2PEngine


class BlockchainNetwork:
    """Manage multiple P2P nodes in a network"""
    
    def __init__(self):
        self.nodes = {}
        self.pow_nodes = []
        self.poa_nodes = []
    
    def add_pow_node(self, node_id, ip="127.0.0.1", port=None, difficulty=2):
        """Add a PoW node to the network"""
        if port is None:
            port = 13245 + len(self.pow_nodes)
        
        engine = P2PEngine(node_id, my_ip=ip, port=port, mode="POW", difficulty=difficulty)
        self.nodes[node_id] = engine
        self.pow_nodes.append(engine)
        return engine
    
    def add_poa_node(self, node_id, ip="127.0.0.1", port=None, authorized_nodes=None):
        """Add a PoA node to the network"""
        if port is None:
            port = 13246 + len(self.poa_nodes)
        
        engine = P2PEngine(node_id, my_ip=ip, port=port, mode="POA", authorized_nodes=authorized_nodes)
        self.nodes[node_id] = engine
        self.poa_nodes.append(engine)
        return engine
    
    def start_all(self):
        """Start all nodes"""
        print("\n" + "="*60)
        print("[Network] Starting all blockchain nodes...")
        print("="*60 + "\n")
        
        for node_id, engine in self.nodes.items():
            engine.start()
            time.sleep(0.5)
    
    def connect_peers(self):
        """Connect all nodes as peers"""
        print("[Network] Connecting peers...\n")
        
        all_engines = list(self.nodes.values())
        for i, engine in enumerate(all_engines):
            for j, peer_engine in enumerate(all_engines):
                if i != j:
                    engine.add_peer(peer_engine.my_ip, peer_engine.port)
    
    def send_test_transaction(self, from_node_id, data):
        """Send a test transaction from a node"""
        if from_node_id in self.nodes:
            self.nodes[from_node_id].send_transaction(data)
        else:
            print(f"[Network] Node {from_node_id} not found")
    
    def print_all_status(self):
        """Print status of all nodes"""
        print("\n" + "="*60)
        print("[Network] Status Report")
        print("="*60)
        
        for engine in self.nodes.values():
            engine.print_status()
    
    def print_all_chains(self):
        """Print all blockchains"""
        print("\n" + "="*60)
        print("[Network] Blockchain Report")
        print("="*60)
        
        for engine in self.nodes.values():
            engine.print_chain()
    
    def stop_all(self):
        """Stop all nodes"""
        print("\n[Network] Stopping all nodes...")
        for engine in self.nodes.values():
            engine.stop()


def run_example():
    """Example: Create a mixed PoW/PoA network"""
    network = BlockchainNetwork()
    
    # Add PoW nodes (difficulty = 2 = 2 leading zeros)
    pow1 = network.add_pow_node("PoW_Node_1", port=13245, difficulty=2)
    pow2 = network.add_pow_node("PoW_Node_2", port=13246, difficulty=2)
    
    # Add PoA nodes with authorized validators
    poa1 = network.add_poa_node("PoA_Node_1", port=13247, 
                               authorized_nodes=["PoA_Node_1", "PoA_Validator_1"])
    poa2 = network.add_poa_node("PoA_Validator_1", port=13248,
                               authorized_nodes=["PoA_Node_1", "PoA_Validator_1"])
    
    # Start all nodes
    network.start_all()
    
    # Connect peers
    time.sleep(1)
    network.connect_peers()
    
    # Send some test transactions
    print("\n[Example] Sending test transactions...\n")
    time.sleep(2)
    
    network.send_test_transaction("PoW_Node_1", "Test transaction 1")
    time.sleep(2)
    
    network.send_test_transaction("PoA_Node_1", "Authority transaction 1")
    time.sleep(2)
    
    # Print status
    time.sleep(3)
    network.print_all_status()
    
    # Print chains
    time.sleep(2)
    network.print_all_chains()
    
    # Keep running
    try:
        print("\n[Example] Network running. Press Ctrl+C to stop...\n")
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n[Example] Shutting down network...")
        network.stop_all()


if __name__ == "__main__":
    run_example()
