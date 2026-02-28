"""
SQLite Database Initialization for Aurex Blockchain PoW
- Shared DB: DB/database.sqlite3 (nodes registry, etc.)
- Per-node ledger: blockchain/node_{port}.sqlite3 (blocks, transactions)
"""

import sqlite3
import os
from pathlib import Path

# Shared database in parent DB folder
DB_FOLDER = Path(__file__).parent.parent / "DB"
DB_FOLDER.mkdir(exist_ok=True)
DB_PATH = str(DB_FOLDER / "database.sqlite3")

# Per-node ledger directory (blockchain folder)
BLOCKCHAIN_DIR = Path(__file__).parent
BLOCKCHAIN_DIR.mkdir(exist_ok=True)


def get_node_db_path(port):
    """Path to this node's ledger DB (node_{port}.sqlite3)."""
    return str(BLOCKCHAIN_DIR / f"node_{port}.sqlite3")


def init_node_database(port):
    """Initialize SQLite ledger for a single node: blocks + transactions."""
    path = get_node_db_path(port)
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS blocks (
            "index" INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            prev_hash TEXT NOT NULL,
            current_hash TEXT NOT NULL,
            nonce INTEGER NOT NULL,
            miner_id TEXT NOT NULL,
            signature TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            block_hash TEXT NOT NULL,
            sender TEXT NOT NULL,
            data TEXT NOT NULL,
            signature TEXT,
            start_timestamp TEXT,
            end_timestamp TEXT
        )
    ''')
    # Migrate existing DBs: add columns if missing
    for col in ('start_timestamp', 'end_timestamp'):
        try:
            cursor.execute(f'ALTER TABLE transactions ADD COLUMN {col} TEXT')
        except sqlite3.OperationalError:
            pass
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocks_index ON blocks("index")')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_blocks_current_hash ON blocks(current_hash)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_tx_block_hash ON transactions(block_hash)')
    conn.commit()
    conn.close()
    print(f" Node ledger initialized at {path}")


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
            verified INTEGER DEFAULT 0
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
            FOREIGN KEY (block_id) REFERENCES blocks(id)
        )
    ''')
    
    # Assets table (user assets on blockchain)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id TEXT UNIQUE NOT NULL,
            asset_name TEXT NOT NULL,
            owner TEXT NOT NULL,
            block_hash TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
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
