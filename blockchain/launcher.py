"""
Aurex Blockchain System - Multi-Node Launcher with Separate Windows
Each node runs in its own subprocess window. Supports --port and --difficulty per run.
RPC server: run rpc_server.py separately (socket-based, no Flask); submit_transaction + block_confirmation listener.
"""

import subprocess
import time
import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from db_init import init_database, init_node_database
from config import NODE_PORTS, NUM_NODES


class SimpleBlockchainManager:
    """Manage multiple PoW nodes using subprocess (5 nodes by default)"""
    
    def __init__(self, num_nodes=None, difficulty=3):
        """Initialize the blockchain system. num_nodes defaults to 5 (all NODE_PORTS)."""
        self.num_nodes = num_nodes if num_nodes is not None else NUM_NODES
        self.difficulty = difficulty
        self.processes = []
        self.ports = NODE_PORTS[:self.num_nodes]
        
        print("\n" + "="*70)
        print("⛓️  AUREX BLOCKCHAIN - PoW SYSTEM")
        print("="*70)
        print(f"Nodes:        {self.num_nodes} (ports: {self.ports})")
        print(f"Difficulty:   {self.difficulty} leading zeros")
        print(f"Network:      127.0.0.1 (localhost)")
        print("="*70 + "\n")
        sys.stdout.flush()
    
    def setup_database(self):
        """Initialize shared DB and per-node ledger DBs"""
        print("[DB] Initializing shared database...", flush=True)
        sys.stdout.flush()
        init_database()
        for port in self.ports:
            init_node_database(port)
        print("[DB] Ready\n", flush=True)
        sys.stdout.flush()
    
    def start_all_nodes(self):
        """Start all nodes in separate subprocess windows (--port and --difficulty from config)"""
        print("[NODES] Launching in separate windows...\n", flush=True)
        sys.stdout.flush()
        
        for i, port in enumerate(self.ports, 1):
            node_name = f"PoW_Node_{i}"
            script_path = os.path.join(os.path.dirname(__file__), f"_node_{i}.py")
            
            # Write node script with better error handling
            script_content = f'''import sys
import os
import traceback
sys.path.insert(0, r"{os.path.dirname(__file__)}")

try:
    from blockchain_node import BlockchainNode
    
    node = BlockchainNode(
        node_name="{node_name}",
        host='127.0.0.1',
        port={port},
        difficulty={self.difficulty}
    )
    node.start()
    while node.running:
        import time
        time.sleep(1)
except Exception as e:
    print(f"FATAL ERROR in {node_name}: {{e}}")
    traceback.print_exc()
    sys.exit(1)
'''
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            # Launch in separate window
            cmd = f'start "Aurex - {node_name}" cmd /k python "{script_path}"'
            try:
                process = subprocess.Popen(cmd, shell=True)
                self.processes.append((node_name, process))
                print(f"✅ {node_name} launched (port {port})", flush=True)
                time.sleep(0.5)
            except Exception as e:
                print(f"❌ Failed to launch {node_name}: {e}", flush=True)
        
        sys.stdout.flush()
        print(f"\n[NODES] All {len(self.processes)} nodes launched\n", flush=True)
        sys.stdout.flush()
    
    def keep_running(self):
        """Keep nodes running in separate windows (don't monitor)"""
        try:
            print("[SYSTEM] Running - press Ctrl+C to stop\n", flush=True)
            sys.stdout.flush()
            
            # Just keep the launcher alive - nodes are in separate windows
            while True:
                time.sleep(1)
        
        except KeyboardInterrupt:
            print("\n[SYSTEM] Shutting down...", flush=True)
            sys.stdout.flush()
            for node_name, process in self.processes:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except:
                    process.kill()
            print("[SYSTEM] Stopped\n", flush=True)
            sys.stdout.flush()
            sys.exit(0)
    
    def run(self):
        """Run the full system"""
        try:
            self.setup_database()
            self.start_all_nodes()
            self.keep_running()
        except Exception as e:
            print(f"❌ Error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            sys.exit(1)


def main():
    """Main entry point. --nodes (default 5), --difficulty (default 3)."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Aurex Blockchain System')
    parser.add_argument('--nodes', type=int, default=NUM_NODES, help='Number of PoW nodes (max 5)')
    parser.add_argument('--difficulty', type=int, default=3, help='Mining difficulty (leading zeros)')
    args = parser.parse_args()
    
    manager = SimpleBlockchainManager(
        num_nodes=min(args.nodes, NUM_NODES),
        difficulty=args.difficulty
    )
    manager.run()


if __name__ == "__main__":
    main()
