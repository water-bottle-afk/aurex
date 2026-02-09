import sys
import os
import traceback
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from blockchain_node import BlockchainNode

    node = BlockchainNode(
        node_name="PoW_Node_5",
        host='127.0.0.1',
        port=13249,
        difficulty=3
    )
    node.start()
    while node.running:
        import time
        time.sleep(1)
except Exception as e:
    print(f"FATAL ERROR in PoW_Node_5: {e}")
    traceback.print_exc()
    sys.exit(1)
