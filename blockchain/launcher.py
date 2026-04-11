"""
Simple launcher: starts N PoW nodes as subprocesses.
Each subprocess instantiates BlockchainNode and blocks in a loop.
"""

import argparse
import subprocess
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

from db_init import init_database, init_node_database
from config import NODE_PORTS, NUM_NODES


def _child_code(node_name, host, port, difficulty):
    return (
        "import multiprocessing, time; "
        "from blockchain_node import BlockchainNode; "
        f"n=BlockchainNode(node_name='{node_name}', host='{host}', port={port}, difficulty={difficulty}); "
        "multiprocessing.freeze_support(); "
        "n.start()"
    )


def main():
    parser = argparse.ArgumentParser(description="Aurex PoW Launcher")
    parser.add_argument("--nodes", type=int, default=NUM_NODES)
    parser.add_argument("--difficulty", type=int, default=3)
    args = parser.parse_args()

    ports = NODE_PORTS[: min(args.nodes, NUM_NODES)]
    init_database()
    for port in ports:
        init_node_database(port)

    for i, port in enumerate(ports, 1):
        node_name = f"PoW_Node_{i}"
        code = _child_code(node_name, "127.0.0.1", port, args.difficulty).replace('"', '\\"')
        cmd = f'start "Aurex - {node_name}" cmd /k python -c "{code}"'
        subprocess.Popen(cmd, shell=True, cwd=os.path.dirname(__file__))
        print(f"{node_name} launched in new window (port {port})", flush=True)
        time.sleep(0.1)

    try:
        sys.exit(0)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
