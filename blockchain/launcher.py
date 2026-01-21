"""
Aurex Blockchain System - Multi-Node Launcher with Separate Windows
Each node runs in its own subprocess window for independent monitoring
"""

import subprocess
import time
import sys
import os
import threading

# Add current directory to path
sys.path.insert(0, os.path.dirname(__file__))

from db_init import init_database


class SimpleBlockchainManager:
    """Manage multiple PoW nodes using subprocess"""
    
    def __init__(self, num_nodes=3, difficulty=3):
        """Initialize the blockchain system"""
        self.num_nodes = num_nodes
        self.difficulty = difficulty
        self.processes = []
        
        print("\n" + "="*70)
        print("⛓️  AUREX BLOCKCHAIN - PoW SYSTEM")
        print("="*70)
        print(f"Nodes:        {num_nodes}")
        print(f"Difficulty:   {difficulty} leading zeros")
        print(f"Network:      127.0.0.1 (localhost)")
        print("="*70 + "\n")
        sys.stdout.flush()
    
    def setup_database(self):
        """Initialize database"""
        print("[DB] Initializing...", flush=True)
        sys.stdout.flush()
        init_database()
        print("[DB] Ready\n", flush=True)
        sys.stdout.flush()
    
    def start_all_nodes(self):
        """Start all nodes in separate subprocess windows"""
        print("[NODES] Launching in separate windows...\n", flush=True)
        sys.stdout.flush()
        
        ports = [13245, 13246, 13247][:self.num_nodes]
        
        for i, port in enumerate(ports, 1):
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
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Aurex Blockchain System')
    parser.add_argument('--nodes', type=int, default=3, help='Number of PoW nodes')
    parser.add_argument('--difficulty', type=int, default=3, help='Mining difficulty')
    args = parser.parse_args()
    
    manager = SimpleBlockchainManager(num_nodes=args.nodes, difficulty=args.difficulty)
    manager.run()


if __name__ == "__main__":
    main()
