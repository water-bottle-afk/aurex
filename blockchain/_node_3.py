import sys
import os
import traceback
sys.path.insert(0, r"C:\dev\aurex\blockchain")

GATEWAY_HOST = os.environ.get("AUREX_GATEWAY_HOST", "127.0.0.1")
GATEWAY_PORT = int(os.environ.get("AUREX_GATEWAY_PORT", "5000"))

try:
    from blockchain_node import BlockchainNode
    
    node = BlockchainNode(
        node_name="PoW_Node_3",
        host='127.0.0.1',
        port=13247,
        difficulty=2,
        gateway_host=GATEWAY_HOST,
        gateway_port=GATEWAY_PORT,
    )
    node.start()
    while node.running:
        import time
        time.sleep(1)
except Exception as e:
    print(f"FATAL ERROR in PoW_Node_3: {e}")
    traceback.print_exc()
    sys.exit(1)
