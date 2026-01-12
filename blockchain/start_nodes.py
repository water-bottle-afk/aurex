"""
Multi-Node Launcher - Start all 5 PoW nodes for local testing
Ports: 11111, 22222, 33333, 44444, 55555
"""

import threading
import time
import sys
from pow_node import PoWNode
from db_init import init_database

NODES_CONFIG = [
    {'port': 11111},
    {'port': 22222},
    {'port': 33333},
    {'port': 44444},
    {'port': 55555},
]

def start_node(port):
    """Start a single node (miner + validator)"""
    node = PoWNode(host='0.0.0.0', port=port)
    
    # Start listening thread
    listen_thread = threading.Thread(target=node.start_listening)
    listen_thread.daemon = True
    listen_thread.start()
    
    # Discover nodes after a delay
    time.sleep(2)
    node.discover_nodes()
    
    # Mine blocks
    block_num = 0
    while True:
        try:
            block_num += 1
            print(f"\n[PORT {port}] Mining block #{block_num}...")
            node.mine_block(f"Block #{block_num} from port {port}")
            time.sleep(5)  # Wait before mining next block
        except KeyboardInterrupt:
            node.stop()
            break
        except Exception as e:
            print(f"❌ Error in mining loop: {e}")
            time.sleep(1)

def main():
    """Start all nodes"""
    print("=" * 60)
    print("🚀 AUREX BLOCKCHAIN - MULTI-NODE PoW NETWORK")
    print("=" * 60)
    
    # Initialize database
    init_database()
    
    # Start each node in separate thread
    threads = []
    for config in NODES_CONFIG:
        thread = threading.Thread(
            target=start_node,
            args=(config['port'],),
            daemon=True
        )
        threads.append(thread)
        thread.start()
        print(f"✅ Started node on port {config['port']} (full-node: miner + validator)")
        time.sleep(1)  # Stagger startup
    
    print("\n" + "=" * 60)
    print("📡 All nodes started! Press Ctrl+C to stop")
    print("=" * 60)
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        sys.exit(0)

if __name__ == "__main__":
    main()
