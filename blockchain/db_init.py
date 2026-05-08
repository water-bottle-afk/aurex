"""
SQLite Database Initialization for Aurex Blockchain PoW
- Shared DB: DB/database.sqlite3 (nodes registry, etc.)
- PoW nodes persist ledgers as per-node JSON files (see pow_node.py)
"""

import sqlite3
import os
from pathlib import Path

# Shared database in parent DB folder (marketplace.db is the live DB)
DB_FOLDER = Path(__file__).parent.parent / "DB"
DB_FOLDER.mkdir(exist_ok=True)
DB_PATH = str(DB_FOLDER / "marketplace.db")

# Per-node ledger directory (blockchain folder); each node gets its own subfolder
BLOCKCHAIN_DIR = Path(__file__).parent
BLOCKCHAIN_DB_DIR = BLOCKCHAIN_DIR / "BLOCKCHAIN_DB"
BLOCKCHAIN_DB_DIR.mkdir(exist_ok=True)
BLOCKCHAIN_DB_PATH = str(BLOCKCHAIN_DB_DIR / "gateway_ledger.json")


def get_node_db_path(port):
    """Path to the shared ledger DB."""
    return BLOCKCHAIN_DB_PATH


def init_node_database(port):
    """No-op: PoW nodes persist ledgers as JSON (see pow_node.py)."""
    ledger_dir = Path(__file__).parent / "BLOCKCHAIN_DB"
    ledger_dir.mkdir(exist_ok=True)
    print(f" Node ledger uses JSON at {ledger_dir}")


def get_node_db_connection(port):
    """Get a connection to this node's ledger DB. Call from the thread that will use it."""
    path = get_node_db_path(port)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Users table (from Flask signup/login)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified INTEGER DEFAULT 0,
            wallet_balance REAL DEFAULT 0,
            wallet_updated_at TEXT,
            wallet_public_key TEXT
        )
    ''')
    cursor.execute("PRAGMA table_info(users)")
    user_cols = {row[1] for row in cursor.fetchall()}
    if 'wallet_balance' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN wallet_balance REAL DEFAULT 0")
    if 'wallet_updated_at' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN wallet_updated_at TEXT")
    if 'wallet_public_key' not in user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN wallet_public_key TEXT")

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS wallets (
            username TEXT PRIMARY KEY NOT NULL,
            public_key_hex TEXT NOT NULL,
            key_type TEXT NOT NULL DEFAULT 'ED25519',
            registered_at TEXT NOT NULL
        )
    ''')
    
    # Nodes table (P2P network discovery)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            node_id TEXT UNIQUE NOT NULL,
            host TEXT NOT NULL,
            port INTEGER NOT NULL,
            node_type TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Blocks table (PoW blockchain)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_hash TEXT UNIQUE NOT NULL,
            previous_hash TEXT,
            nonce INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            miner_id TEXT NOT NULL,
            difficulty INTEGER NOT NULL,
            transactions_count INTEGER DEFAULT 0,
            data TEXT
        )
    ''')
    
    # Transactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_hash TEXT UNIQUE NOT NULL,
            from_user TEXT NOT NULL,
            to_user TEXT,
            amount REAL NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            block_id INTEGER,
            status TEXT DEFAULT 'pending',
            is_confirmed_on_chain INTEGER DEFAULT 0,
            FOREIGN KEY (block_id) REFERENCES blocks(id)
        )
    ''')
    cursor.execute("PRAGMA table_info(transactions)")
    tx_cols = {row[1] for row in cursor.fetchall()}
    if 'is_confirmed_on_chain' not in tx_cols:
        cursor.execute("ALTER TABLE transactions ADD COLUMN is_confirmed_on_chain INTEGER DEFAULT 0")
    
    # Assets table (user assets on blockchain)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT UNIQUE NOT NULL,
            asset_name TEXT NOT NULL,
            owner TEXT NOT NULL,
            block_hash TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_confirmed_on_chain INTEGER DEFAULT 0
        )
    ''')
    cursor.execute("PRAGMA table_info(assets)")
    asset_cols = {row[1] for row in cursor.fetchall()}
    if 'is_confirmed_on_chain' not in asset_cols:
        cursor.execute("ALTER TABLE assets ADD COLUMN is_confirmed_on_chain INTEGER DEFAULT 0")
    
    # Mining pool table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mining_pool (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            worker_id TEXT NOT NULL,
            nonce_start INTEGER NOT NULL,
            nonce_end INTEGER NOT NULL,
            completed INTEGER DEFAULT 0,
            solution_nonce INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create indexes for faster queries
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocks_hash ON blocks(block_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_transactions_hash ON transactions(tx_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_nodes_id ON nodes(node_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_assets_id ON assets(asset_id)')
    
    conn.commit()
    conn.close()
    print(f" Database initialized at {DB_PATH}")

def get_db_connection():
    """Get a connection to the SQLite database"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Return rows as dictionaries
    return conn

if __name__ == "__main__":
    init_database()
