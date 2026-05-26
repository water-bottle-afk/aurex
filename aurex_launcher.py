import argparse
import subprocess
import sys
import time
from SharedResources.logging import Logger
from SharedResources.config import GATEWAY_IP, GATEWAY_PORT, SERVER_IP, SERVER_PORT, POW_DIFFICULTY

PYTHON_EXEC = "python"
BLOCKCHAIN_DIR = "Blockchain"
GATEWAY_DIR = "Gateway"
MARKETPLACE_DIR = "Server"
CLIENT_DIR = "Client"

logger = Logger(__file__)


def launch_task(name, command, cwd=""):
    logger.info(f"[+] Starting {name}...")
    return subprocess.Popen(
        ["start", "cmd", "/k", f"title {name} && {command}"],
        cwd=cwd,
        shell=True,
    )


def main():
    parser = argparse.ArgumentParser(description="Aurex orchestrator")
    parser.add_argument(
        "--debug-level", "--DEBUG_LEVEL",
        default="DEBUG",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity passed to all components",
    )
    args = parser.parse_args()

    Logger.set_level(args.debug_level)
    debug_flag = f"--debug-level {args.debug_level}"

    logger.info("=== AUREX PROJECT ORCHESTRATOR ===")

    launch_task(
        "Aurex-Nodes",
        f"{PYTHON_EXEC} Bnode.py --difficulty {POW_DIFFICULTY} --port 14253 {debug_flag}",
        BLOCKCHAIN_DIR,
    )
    time.sleep(2)

    launch_task("Aurex-Gateway", f"{PYTHON_EXEC} gateway.py {debug_flag}", GATEWAY_DIR)
    logger.info("[!] Waiting for Gateway to stabilize...")
    time.sleep(3)

    launch_task("Aurex-Marketplace", f"{PYTHON_EXEC} server_module.py {debug_flag}", MARKETPLACE_DIR)
    time.sleep(2)

    launch_task("Aurex-Client", f"{PYTHON_EXEC} client.py {debug_flag}", CLIENT_DIR)

    logger.info("[SUCCESS] All systems dispatched.")
    logger.info("  - Aurex-Nodes: blockchain PoW nodes (Blockchain/node_*/)")
    logger.info("  - Aurex-Gateway: server<->blockchain relay")
    logger.info("  - Aurex-Server: marketplace server (API, DB, order matching)")
    logger.info("  - Aurex-Client: Flet app")
    logger.info("First time? Go to Settings > Wallet & Identity > Generate My Keys before uploading.")


if __name__ == "__main__":
    main()
    sys.exit(0)
