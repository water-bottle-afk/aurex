import subprocess
import time
import os
import sys

# --- CONFIGURATION ---
# Adjust these paths if your folder structure differs
PYTHON_EXEC = "python"  # Uses your current python environment
BLOCKCHAIN_DIR = "blockchain"
MARKETPLACE_DIR = "Server"
CLIENT_DIR = "."  # Root where main.py lives

def launch_task(name, command, cwd=""):
    print(f"[+] Starting {name}...")
    # opens a new terminal window for each service so you can see logs
    return subprocess.Popen(["start", "cmd", "/k", f"title {name} && {command}"], 
                            cwd=cwd, shell=True)

def main():
    print("=== AUREX PROJECT ORCHESTRATOR ===")
    
    # 1. Start Blockchain Nodes (PoW Launcher)
    # Assuming launcher.py handles starting multiple nodes
    nodes_count = 3
    difficulty = 2
    launch_task("Aurex-Nodes", f"{PYTHON_EXEC} launcher.py --nodes {nodes_count} --difficulty {difficulty}", BLOCKCHAIN_DIR)
    time.sleep(2)

    # 2. Start Blockchain Gateway
    launch_task("Aurex-Gateway", f"{PYTHON_EXEC} gateway_server.py", BLOCKCHAIN_DIR)
    print("[!] Waiting for Gateway to stabilize...")
    time.sleep(3) 

    # 3. Start Marketplace Server
    # Note: Using the renamed 'server_module.py'
    launch_task("Aurex-Marketplace", f"{PYTHON_EXEC} server_module.py", MARKETPLACE_DIR)
    time.sleep(2)

    # 4. Start Flet Client
    launch_task("Aurex-Client", f"{PYTHON_EXEC} main.py", CLIENT_DIR)

    print("\n[SUCCESS] All systems dispatched.")
    print("  • Aurex-Nodes     — blockchain PoW nodes (per-node ledger in blockchain/BLOCKCHAIN_DB/node_*/)")
    print("  • Aurex-Gateway   — signature verify + broadcast (port 5000)")
    print("  • Aurex-Marketplace — TCP marketplace server (port 23456)")
    print("  • Aurex-Client    — Flet desktop app")
    print("\nFirst time? Go to Settings → Wallet & Identity → Generate My Keys before uploading.")

if __name__ == "__main__":
    main()
    sys.exit(0)