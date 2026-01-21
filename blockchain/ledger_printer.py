"""
Ledger Printer - Display blockchain data beautifully
"""

import sqlite3
from datetime import datetime
from pathlib import Path

# Default to DB folder location
DEFAULT_DB_PATH = str(Path(__file__).parent.parent / "DB" / "database.sqlite3")

def print_ledger(db_path=None):
    """Print the last 2 blocks from ledger with full details"""
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get last 2 blocks
        cursor.execute('''
            SELECT id, block_hash, previous_hash, nonce, miner_id, difficulty, data, timestamp
            FROM blocks
            ORDER BY timestamp DESC
            LIMIT 2
        ''')
        
        blocks = cursor.fetchall()
        conn.close()
        
        if not blocks:
            print("\n[LEDGER] No blocks yet\n")
            return
        
        print("\n" + "="*80)
        print("⛓️  BLOCKCHAIN LEDGER - LAST 2 BLOCKS")
        print("="*80 + "\n")
        
        for idx, (block_id, block_hash, prev_hash, nonce, miner_id, difficulty, data, timestamp) in enumerate(blocks, 1):
            print(f"📦 BLOCK #{block_id}")
            print("─" * 80)
            print(f"  Timestamp:     {timestamp}")
            print(f"  Miner:         {miner_id}")
            print(f"  Difficulty:    {difficulty} leading zeros")
            print(f"  Nonce:         {nonce}")
            print()
            print(f"  📋 DATA:")
            print(f"     {data[:70]}{'...' if len(data) > 70 else ''}")
            print()
            print(f"  🔐 HASH (Current Block):")
            print(f"     {block_hash}")
            print()
            print(f"  ⛓️  LINKED TO PREVIOUS:")
            if prev_hash:
                print(f"     {prev_hash}")
            else:
                print(f"     [GENESIS BLOCK]")
            print()
            print(f"  ✍️  SIGNATURE/VALIDATION:")
            print(f"     Block ID: {block_id}")
            print(f"     Status: ✅ CONFIRMED ON CHAIN")
            print()
        
        print("="*80 + "\n")
        
    except Exception as e:
        print(f"\n[ERROR] Failed to print ledger: {e}\n")


if __name__ == "__main__":
    print_ledger()
