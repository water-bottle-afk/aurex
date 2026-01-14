import sys
import os
sys.path.insert(0, r"C:\dev\aurex\blockchain")

from blockchain_node import BlockchainNode

node = BlockchainNode(
    node_name="PoW_Node_1",
    host='127.0.0.1',
    port=13245,
    difficulty=4
)
node.start()
while node.running:
    import time
    time.sleep(1)
