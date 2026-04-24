import os
import subprocess
import sys
import time

PYTHON_EXEC = "python"
BLOCKCHAIN_DIR = "blockchain"
MARKETPLACE_DIR = "Server"
CLIENT_DIR = "."


def launch_task(name, command, cwd=""):
    print(f"[+] Starting {name}...")
    # Use dedicated terminals so local debugging can follow each service log.
    return subprocess.Popen(
        ["start", "cmd", "/k", f"title {name} && {command}"],
        cwd=cwd,
        shell=True,
    )


def main():
    print("=== AUREX PROJECT ORCHESTRATOR ===")

    nodes_count = 4
    difficulty = 1
    launch_task(
        "Aurex-Nodes",
        f"{PYTHON_EXEC} launcher.py --nodes {nodes_count} --difficulty {difficulty}",
        BLOCKCHAIN_DIR,
    )
    time.sleep(2)

    launch_task("Aurex-Gateway", f"{PYTHON_EXEC} gateway_server.py", BLOCKCHAIN_DIR)
    print("[!] Waiting for Gateway to stabilize...")
    time.sleep(3)

    launch_task("Aurex-Marketplace", f"{PYTHON_EXEC} server_module.py", MARKETPLACE_DIR)
    time.sleep(2)

    launch_task("Aurex-Client", f"{PYTHON_EXEC} main.py", CLIENT_DIR)

    print("\n[SUCCESS] All systems dispatched.")
    print("  - Aurex-Nodes: blockchain PoW nodes (blockchain/BLOCKCHAIN_DB/node_*/)")
    print("  - Aurex-Gateway: signature verification + broadcast (port 5000)")
    print("  - Aurex-Marketplace: WSS marketplace server (port 23456)")
    print("  - Aurex-Client: Flet web app over HTTPS")
    print("\nFirst time? Go to Settings > Wallet & Identity > Generate My Keys before uploading.")


if __name__ == "__main__":
    main()
    sys.exit(0)
