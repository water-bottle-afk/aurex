import sys
import os
import traceback
sys.path.insert(0, r"C:\dev\aurex\blockchain")

try:
    from blockchain_node import BlockchainNode
    
    node = BlockchainNode(
        node_name="PoW_Node_2",
        host='127.0.0.1',
        port=13246,
        difficulty=2
    )
    node.start()
    while node.running:
        import time
        time.sleep(1)
except Exception as e:
    print(f"FATAL ERROR in PoW_Node_2: {e}")
    traceback.print_exc()
    sys.exit(1)
