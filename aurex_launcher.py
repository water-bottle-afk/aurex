import os
import subprocess
import sys
import time
from SharedResources.logging import Logger

PYTHON_EXEC = "python"
BLOCKCHAIN_DIR = "Blockchain"
GATEWAY_DIR = "Gateway"
MARKETPLACE_DIR = "Server"
CLIENT_DIR = "Client"
logger = Logger(__file__)


def launch_task(name, command, cwd=""):
    logger.info(f"[+] Starting {name}...")
    # Use dedicated terminals so local debugging can follow each service log.
    return subprocess.Popen(
        ["start", "cmd", "/k", f"title {name} && {command}"],
        cwd=cwd,
        shell=True,
    )


def main():
    logger.info("=== AUREX PROJECT ORCHESTRATOR ===")

    nodes_count = 1
    difficulty = 1
    launch_task(
        "Aurex-Nodes",
        f"{PYTHON_EXEC} Bnode.py --ip {"10.100.102.58"} --difficulty {2} --port {14253}",
        BLOCKCHAIN_DIR,
    )
    time.sleep(2)

    launch_task("Aurex-Gateway", f"{PYTHON_EXEC} gateway.py", GATEWAY_DIR)
    logger.info("[!] Waiting for Gateway to stabilize...")
    time.sleep(3)

    launch_task("Aurex-Marketplace", f"{PYTHON_EXEC} server_module.py", MARKETPLACE_DIR)
    time.sleep(2)

    launch_task("Aurex-Client", f"{PYTHON_EXEC} client.py", CLIENT_DIR)

    logger.info("[SUCCESS] All systems dispatched.")
    logger.info("  - Aurex-Nodes: blockchain PoW nodes (blockchain/BLOCKCHAIN_DB/node_*/)")
    logger.info("  - Aurex-Gateway: server<->blockchain relay")
    logger.info("  - Aurex-Server: marketplace server (API, DB, order matching, etc.)")
    logger.info("  - Aurex-Client: Flet app")
    logger.info("First time? Go to Settings > Wallet & Identity > Generate My Keys before uploading.")


if __name__ == "__main__":
    main()
    sys.exit(0)
