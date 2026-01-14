# Aurex Blockchain System Documentation

## Table of Contents
1. [Overview](#overview)
2. [System Architecture](#system-architecture)
3. [File Structure & Purpose](#file-structure--purpose)
4. [Consensus Mechanisms](#consensus-mechanisms)
5. [Workflow Diagrams](#workflow-diagrams)
6. [Data Flow](#data-flow)
7. [Running the System](#running-the-system)
8. [Debugging Guide](#debugging-guide)

---

## Overview

The Aurex Blockchain is a **distributed, peer-to-peer consensus system** that supports two consensus mechanisms:

- **Proof of Work (PoW)**: Traditional mining-based consensus
- **Proof of Authority (PoA)**: Trusted authority-based consensus

The system implements a **gossip protocol** for node discovery and information propagation across the network.

---

## System Architecture

### High-Level Design

```
┌─────────────────────────────────────────────────────┐
│           Aurex Blockchain Network                   │
│  (Distributed P2P System with Gossip Protocol)      │
└─────────────────────────────────────────────────────┘
         ↓         ↓         ↓         ↓
    ┌────────┬────────┬────────┬────────┐
    │ Node 1 │ Node 2 │ Node 3 │ Node 4 │
    │ (PoW)  │ (PoW)  │ (PoA)  │ (PoA)  │
    └────────┴────────┴────────┴────────┘
         ↓         ↓         ↓         ↓
    ┌──────────────────────────────────────┐
    │   P2P Engine (Universal)              │
    │ - Node Discovery (Gossip Protocol)    │
    │ - Block Broadcasting                  │
    │ - Transaction Handling                │
    └──────────────────────────────────────┘
         ↓         ↓         ↓         ↓
    ┌────────┬────────┬────────┬────────┐
    │ PoW    │ PoW    │ PoA    │ PoA    │
    │Manager │Manager │Manager │Manager │
    └────────┴────────┴────────┴────────┘
         ↓         ↓         ↓         ↓
    ┌────────┬────────┬────────┬────────┐
    │ PoW    │ PoW    │ PoA    │ PoA    │
    │ Node   │ Node   │ Node   │ Node   │
    └────────┴────────┴────────┴────────┘
         ↓         ↓         ↓         ↓
    ┌──────────────────────────────────────┐
    │      SQLite Ledger Database           │
    │ - Blocks Table                        │
    │ - Transactions Table                  │
    │ - Assets Table                        │
    │ - Nodes Table (Peer Discovery)        │
    └──────────────────────────────────────┘
```

---

## File Structure & Purpose

### Core Consensus Files

#### **1. `pow_node.py`** (PoW Consensus Node)
**When Used**: When running Proof of Work blockchain nodes
- **Responsible for**:
  - Mining blocks (solving PoW puzzle)
  - Validating incoming blocks against difficulty requirement
  - Managing pending transactions
  - Database registration and node discovery
  - P2P communication
- **Key Methods**:
  - `mine_block()`: Iterate nonces until difficulty met
  - `validate_block()`: Check hash meets difficulty
  - `discover_nodes()`: Gossip protocol - find nodes in network
  - `broadcast_message()`: Send block/transaction to peers
- **Ports**: 11111, 22222, 33333, 44444, 55555 (default)

#### **2. `poa_node.py`** (PoA Consensus Node)
**When Used**: When running Proof of Authority blockchain nodes
- **Responsible for**:
  - Creating blocks signed by authority
  - Validating signatures from trusted nodes
  - Managing block chain
  - Authority check
- **Key Methods**:
  - `sign_data()`: Sign data if node is authority
  - `validate_signature()`: Verify authorized node signature
  - `create_block()`: Create signed block
  - `add_block()`: Add block to chain
- **Role**: Authority nodes sign blocks; regular nodes validate

### Manager Files

#### **3. `manager_pow.py`** (PoW Manager)
**When Used**: Wraps PoW consensus logic for P2P integration
- **Responsible for**:
  - Managing PoW peer connections
  - Broadcasting blocks with PoW verification
  - Handling incoming messages (blocks, transactions)
  - Mining coordination
- **Key Methods**:
  - `validate_block()`: Check difficulty requirement
  - `broadcast_block()`: Send block to all peers
  - `start()`: Start listening server
  - `_handle_message()`: Process P2P messages

#### **4. `manager_poa.py`** (PoA Manager)
**When Used**: Wraps PoA consensus logic for P2P integration
- **Responsible for**:
  - Managing PoA peer connections
  - Signature validation
  - Authority node management
  - Block broadcasting
- **Key Methods**:
  - `validate_signature()`: Verify authorized signer
  - `broadcast_block()`: Send block to peers
  - `start()`: Start listening server

### Network & P2P Files

#### **5. `p2p_engine.py`** (Universal P2P Engine)
**When Used**: ALL nodes use this - it's the communication backbone
- **Responsible for**:
  - Universal P2P networking (works with PoW or PoA)
  - Peer management and discovery
  - Message routing
  - Server socket setup
- **Key Methods**:
  - `add_peer()`: Register peer address
  - `start()`: Start P2P server
  - `send_transaction()`: Send transaction message
  - `print_chain()`: Display blockchain
  - `print_status()`: Node status report

#### **6. `network.py`** (Network Manager)
**When Used**: For coordinating multiple nodes in testing
- **Responsible for**:
  - Creating and configuring multiple nodes
  - Connecting nodes as peers
  - Network-wide operations
- **Key Methods**:
  - `add_pow_node()`: Add PoW node to network
  - `add_poa_node()`: Add PoA node to network
  - `start_all()`: Start all nodes
  - `connect_peers()`: Create peer connections
  - `send_test_transaction()`: Test transaction

### Database Files

#### **7. `db_init.py`** (Database Initialization)
**When Used**: When system starts (initializes SQLite database)
- **Responsible for**:
  - Creating SQLite database schema
  - Setting up tables: blocks, transactions, assets, nodes, users
  - Creating indexes for performance
- **Tables Created**:
  ```
  users                 - User accounts
  nodes                 - P2P node registry
  blocks                - Blockchain blocks
  transactions          - Transaction ledger
  assets                - Digital assets
  mining_pool           - Mining coordination
  ```

### Configuration & Utilities

#### **8. `config.py`** (Configuration Constants)
**When Used**: Used by all files for consistent constants
- **Defines**:
  - Port numbers (13245 for PoW, 13246 for PoA)
  - Block field names
  - Message types
  - Consensus modes
  - Error messages
  - Socket parameters

#### **9. `utils.py`** (Helper Functions)
**When Used**: Used by all consensus and manager files
- **Provides**:
  - Data validation functions
  - Hash and crypto helpers
  - Block creation helpers
  - Message creation utilities
  - Logging utilities
- **Key Functions**:
  - `is_valid_block()`: Validate block structure
  - `is_valid_peer_address()`: Verify IP:port
  - `create_pow_block()`: Build PoW block
  - `create_poa_block()`: Build PoA block
  - `send_to_peer()`: Network communication

#### **10. `logging_config.py`** (Logging Setup)
**When Used**: On startup to configure logging
- **Configures**:
  - Log level (INFO, DEBUG, ERROR)
  - Log format with timestamps
  - File and console output

### Entry Point Files

#### **11. `start_nodes.py`** (Old Multi-Node Starter)
**When Used**: Legacy PoW node launcher
- **Functionality**:
  - Starts 5 PoW nodes on ports 11111-55555
  - Uses old PoWNode class directly
  - ⚠️ Not recommended - use `run_blockchain.py` instead

#### **12. `run_blockchain.py`** (Main System Launcher - NEW)
**When Used**: START HERE - Master node controller
- **Functionality**:
  - Initialize database
  - Start 3-5 nodes with mixed PoW/PoA
  - Create peer connections automatically
  - Send test transactions
  - Monitor blockchain state
  - Display ledger contents
- **Usage**: `python run_blockchain.py`

---

## Consensus Mechanisms

### Proof of Work (PoW)

**How It Works**:
1. Node receives data to mine
2. Iterates through nonces: 0, 1, 2, 3, ...
3. For each nonce: `hash(data + nonce)`
4. Checks if hash has `N` leading zeros (difficulty)
5. When found: broadcasts block to network

**Difficulty Levels**:
- `1` = 1 leading zero (very easy)
- `2` = 2 leading zeros (easy - default)
- `3` = 3 leading zeros (medium)
- `4` = 4 leading zeros (hard)

**Example** (difficulty = 2):
```
Nonce: 0     → hash: abcd...  ❌ (doesn't start with 00)
Nonce: 1     → hash: 1234...  ❌
...
Nonce: 247   → hash: 00f2...  ✅ (starts with 00!)
Block found! Broadcast to peers.
```

### Proof of Authority (PoA)

**How It Works**:
1. Authority nodes create blocks
2. Authority nodes sign blocks with signature
3. Other nodes receive and validate signature
4. If valid: add to chain

**Authority Requirement**:
- Only nodes in `authorized_nodes` list can sign
- Signature format: `SIG_{node_id}_{data_hash}`
- Regular nodes validate but don't sign

---

## Workflow Diagrams

### Mining Workflow (PoW)

```
┌──────────────────┐
│  Start Mining    │
└────────┬─────────┘
         │
         ↓
┌──────────────────────────────┐
│  Get Data to Mine            │
│  Nonce = 0                   │
└────────┬─────────────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Calculate Hash              │
│  hash = SHA256(data + nonce) │
└────────┬─────────────────────┘
         │
         ↓
    ┌────────────────────┐
    │  Check Difficulty  │
    │  hash == "00..."?  │
    └─┬──────────────┬───┘
      │              │
     ✅ YES         ❌ NO
      │              │
      ↓              ↓
   ┌────────┐   ┌──────────────┐
   │ Found! │   │ Nonce += 1   │
   └────┬───┘   │ Try again    │
        │       └───┬──────────┘
        │           │
        │           └─ (loop back)
        │
        ↓
   ┌─────────────────────────────┐
   │  Create Block               │
   │  {data, nonce, hash, miner} │
   └────────┬────────────────────┘
            │
            ↓
   ┌──────────────────────────────┐
   │  Broadcast to All Peers      │
   │  Message: BLOCK_FOUND        │
   └────────┬─────────────────────┘
            │
            ↓
   ┌──────────────────────────────┐
   │  Peers Validate & Add Block  │
   │  → Store in blocks table     │
   └──────────────────────────────┘
```

### Gossip Protocol Workflow

```
┌──────────────────┐
│   Node Starts    │
└────────┬─────────┘
         │
         ↓
┌──────────────────────────────┐
│  Node Discovery              │
│  Query: "active nodes"       │
│  Source: database            │
└────────┬─────────────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Get Known Nodes List        │
│  known_nodes = {             │
│    node_id: (host, port),    │
│    ...                       │
│  }                           │
└────────┬─────────────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Connect to Peers            │
│  Send to: (host:port)        │
└────────┬─────────────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Receive Blocks/Messages     │
│  Message Types:              │
│  - ping / pong              │
│  - node_list               │
│  - new_block               │
│  - new_transaction         │
└────────┬─────────────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Propagate to Other Peers    │
│  (Gossip: spread info)       │
└──────────────────────────────┘
```

### Transaction Flow

```
┌──────────────────────┐
│  User/App sends tx   │
└────────┬─────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Node receives transaction   │
│  Validates format            │
└────────┬─────────────────────┘
         │
         ↓
    ┌──────────────────┐
    │  Valid?          │
    └─┬──────────────┬─┘
      │              │
     ✅ YES         ❌ NO
      │              │
      ↓              ↓
┌────────────┐   ┌───────────┐
│ Add to     │   │ Reject    │
│ mempool    │   │ (invalid) │
└────┬───────┘   └───────────┘
     │
     ↓
┌──────────────────────────────┐
│  Broadcast to Peers          │
│  Message: NEW_TRANSACTION    │
└────────┬─────────────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Include in Next Block       │
│  During Mining/Consensus     │
└────────┬─────────────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Block Mined/Signed          │
│  Transaction committed       │
└────────┬─────────────────────┘
         │
         ↓
┌──────────────────────────────┐
│  Store in Database           │
│  transactions table          │
│  Status: 'committed'         │
└──────────────────────────────┘
```

---

## Data Flow

### From User Input → Ledger

```
Web Form
   ↓
Flask Backend (python_files/run_server.py)
   ↓
P2P Engine (p2p_engine.py)
   ↓
Manager (manager_pow.py or manager_poa.py)
   ↓
Consensus Node (pow_node.py or poa_node.py)
   ↓
Mining/Signing Process
   ↓
Block Creation
   ↓
Peer Broadcasting (Gossip)
   ↓
Validation (all nodes)
   ↓
Database Storage (db_init.py)
   ↓
SQLite Ledger (database.sqlite3)
   ├─ blocks table
   ├─ transactions table
   └─ assets table
```

### Block Structure

```json
{
  "index": 0,
  "timestamp": 1610547600.123,
  "data": "Transaction data",
  "previous_hash": "0000abc...",
  
  /* PoW Only */
  "nonce": 247,
  "hash": "0012def...",
  "miner": "PoW_Node_1",
  
  /* PoA Only */
  "signer_id": "PoA_Authority",
  "signature": "SIG_PoA_Authority_xyz123"
}
```

### Transaction Structure

```json
{
  "id": "tx_hash_123",
  "from_user": "alice@example.com",
  "to_user": "bob@example.com",
  "amount": 10.5,
  "timestamp": "2024-01-14T10:30:00",
  "block_id": 5,
  "status": "committed"
}
```

---

## Running the System

### Quick Start

```bash
cd c:\dev\aurex\blockchain
python run_blockchain.py
```

This will:
1. Initialize SQLite database
2. Start 3 PoW nodes + 2 PoA nodes
3. Auto-connect all nodes as peers
4. Send test transactions
5. Display blockchain state
6. Show ledger contents

### Manual Node Control

```python
from network import BlockchainNetwork
import time

# Create network
network = BlockchainNetwork()

# Add nodes
pow1 = network.add_pow_node("PoW_1", port=13245, difficulty=2)
pow2 = network.add_pow_node("PoW_2", port=13246, difficulty=2)
poa1 = network.add_poa_node("PoA_1", port=13247, authorized_nodes=["PoA_1"])

# Start nodes
network.start_all()
time.sleep(1)

# Connect peers
network.connect_peers()

# Send transactions
network.send_test_transaction("PoW_1", "Data from PoW_1")

# View status
network.print_all_status()
network.print_all_chains()

# Cleanup
network.stop_all()
```

---

## Debugging Guide

### Enable Debug Logging

Edit `config.py`:
```python
LOG_LEVEL = logging.DEBUG  # Instead of INFO
```

Or in code:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Common Issues

#### 1. Port Already in Use
```
Error: [Errno 48] Address already in use
```
**Fix**: Kill process on port or use different port
```bash
netstat -ano | findstr :13245
taskkill /PID <PID> /F
```

#### 2. Database Locked
```
Error: database is locked
```
**Fix**: Remove stale process
```bash
# Delete database.sqlite3 to reset
rm c:\dev\aurex\blockchain\database.sqlite3
```

#### 3. Block Not Mining
**Check**:
- Node is running: `print_status()`
- Difficulty is reasonable (start with 2)
- No errors in logs

**Debug PoW Mining**:
```python
# Add to pow_node.py
for nonce in range(10000000):
    if nonce % 100000 == 0:
        print(f"[{self.node_id}] Mining attempt {nonce}...")
    
    hash_val = self.calculate_hash(data, nonce)
    if self.validate_block(hash_val, nonce):
        print(f"[{self.node_id}] ✅ Block found at nonce {nonce}!")
        return block
```

#### 4. Peers Not Connecting
**Check**:
```python
engine.print_status()  # Should show peer_count > 0
```

**Debug**:
```python
# In p2p_engine.py
print(f"[{self.node_id}] Peers: {self.peers}")
print(f"[{self.node_id}] Peer count: {len(self.peers)}")
```

### Monitoring Commands

```python
# Status of single node
engine.print_status()

# Full chain
engine.print_chain()

# Network overview
network.print_all_status()
network.print_all_chains()

# Query database
import sqlite3
conn = sqlite3.connect('database.sqlite3')
cursor = conn.cursor()
cursor.execute('SELECT * FROM blocks')
print(cursor.fetchall())
```

### Log Files

Logs are written to:
- Console (real-time)
- `blockchain.log` (if configured in logging_config.py)

Look for:
```
[Node_ID] Block validation: ✅
[Node_ID] Broadcast: 4/5 peers
[Node_ID] Error: ...
```

---

## Summary Table

| File | Purpose | When Used | Key Class |
|------|---------|-----------|-----------|
| `pow_node.py` | PoW mining | Always (PoW mode) | `PoWNode` |
| `poa_node.py` | PoA signing | Always (PoA mode) | `PoANode` |
| `manager_pow.py` | PoW peer mgmt | With PoW nodes | `ManagerPoW` |
| `manager_poa.py` | PoA peer mgmt | With PoA nodes | `ManagerPoA` |
| `p2p_engine.py` | P2P networking | All nodes | `P2PEngine` |
| `network.py` | Multi-node control | Testing | `BlockchainNetwork` |
| `db_init.py` | Database setup | Startup | Functions |
| `config.py` | Constants | All files | Constants |
| `utils.py` | Helpers | All files | Functions |
| `logging_config.py` | Logging | Startup | Functions |
| `run_blockchain.py` | **Main launcher** | **START HERE** | Functions |

---

## Next Steps

1. **Run the system**: `python run_blockchain.py`
2. **Check ledger**: Query `blocks` and `transactions` tables
3. **Test transactions**: Send test data between nodes
4. **Monitor logs**: Watch console for block creation
5. **Scale up**: Add more nodes as needed

