# Gossip Protocol Implementation Guide

## Overview

The Aurex Blockchain implements a **gossip protocol** for node discovery and information propagation across the P2P network. This document explains how it works and how to use it.

---

## What is a Gossip Protocol?

A gossip protocol is a mechanism where:
1. Each node maintains a list of known nodes
2. Nodes periodically exchange information with peers
3. Information spreads through the network like gossip spreads in a community
4. Eventually, all nodes know about all transactions and blocks

**Advantages**:
- ✅ Decentralized (no central server needed)
- ✅ Resilient (works even if some nodes go down)
- ✅ Self-healing (new nodes discover network automatically)
- ✅ Scalable (bandwidth usage grows logarithmically)

---

## Current Implementation in Aurex

### 1. Node Discovery (`pow_node.py`)

**Location**: `discover_nodes()` method

```python
def discover_nodes(self):
    """
    Discover known nodes from database
    This implements gossip protocol - get list of nearby nodes
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Query all active nodes from database
        cursor.execute(
            'SELECT node_id, host, port FROM nodes WHERE status = "active" AND node_id != ?',
            (self.node_id,)
        )
        nodes = cursor.fetchall()
        
        for node in nodes:
            node_id, host, port = node
            self.known_nodes[node_id] = (host, port)
            print(f"📍 Discovered node: {node_id} at {host}:{port}")
        
        conn.close()
```

**How it works**:
1. Node queries database for all active nodes
2. Creates list: `{node_id: (host, port), ...}`
3. Stores in `self.known_nodes`
4. Uses this list to broadcast messages

### 2. Message Broadcasting (`pow_node.py`)

**Location**: `broadcast_message()` method

```python
def broadcast_message(self, message_type, data):
    """Broadcast message to all known nodes"""
    message = {
        'type': message_type,
        'node_id': self.node_id,
        'timestamp': datetime.now().isoformat(),
        'data': data
    }
    
    # Send to every known node
    for node_id, (host, port) in self.known_nodes.items():
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((host, port))
            sock.send(json.dumps(message).encode())
            sock.close()
            print(f"📤 Broadcast to {node_id}")
        except Exception as e:
            print(f"⚠️ Failed to reach {node_id}: {e}")
```

**How it works**:
1. Create message with type, sender, timestamp, data
2. Connect to each known node
3. Send JSON message
4. Handle failures gracefully (node might be offline)

### 3. P2P Connection Handling (`manager_pow.py`)

**Location**: `_handle_message()` method

```python
def _handle_message(self, client, addr):
    """Handle incoming message from peer"""
    data = client.recv(SOCKET_BUFFER_SIZE).decode()
    message = json.loads(data)
    msg_type = message.get(MSG_FIELD_TYPE)
    
    if msg_type == MSG_TYPE_BLOCK_FOUND:
        # Process block
        self._handle_block_found(message)
    elif msg_type == MSG_TYPE_NEW_TRANSACTION:
        # Process transaction
        self._handle_transaction(message)
```

**How it works**:
1. Node listens on socket
2. Accepts incoming connections
3. Receives message JSON
4. Routes to appropriate handler
5. Propagates to other peers

---

## Message Types in Gossip Protocol

### 1. BLOCK_FOUND
```json
{
  "type": "BLOCK_FOUND",
  "sender": "PoW_Node_1",
  "content": {
    "index": 5,
    "hash": "00123abc...",
    "nonce": 247,
    "data": "Transaction data",
    "timestamp": 1610547600.123,
    "miner": "PoW_Node_1"
  }
}
```

**Flow**:
```
Node A mines block
    ↓
Broadcast BLOCK_FOUND to all peers
    ↓
Node B receives, validates, adds to chain
    ↓
Node B broadcasts to its peers
    ↓
Block spreads through network (gossip)
```

### 2. NEW_TRANSACTION
```json
{
  "type": "NEW_TRANSACTION",
  "sender": "PoW_Node_1",
  "data": "Transfer 100 coins from Alice to Bob"
}
```

**Flow**:
```
User submits transaction
    ↓
Node receives via API
    ↓
Add to mempool (pending transactions)
    ↓
Broadcast NEW_TRANSACTION to peers
    ↓
Include in next mined block
```

### 3. PING / PONG (Health Check)
```json
{
  "type": "ping",
  "node_id": "PoW_Node_1",
  "timestamp": "2024-01-14T10:30:00"
}
```

**Response**:
```json
{
  "type": "pong",
  "node_id": "PoW_Node_1",
  "timestamp": "2024-01-14T10:30:00"
}
```

### 4. NODE_LIST (Peer Discovery)
```json
{
  "type": "node_list",
  "node_id": "PoW_Node_1",
  "nodes": [
    {"node_id": "PoW_Node_2", "host": "127.0.0.1", "port": 22222},
    {"node_id": "PoW_Node_3", "host": "127.0.0.1", "port": 33333}
  ]
}
```

---

## Complete Gossip Flow Example

### Scenario: Node A mines a block

```
Time 0:00
┌─ Node A ─────────────────────────────────────┐
│ Mines block: hash=00abcd... nonce=247        │
│ known_nodes = {B, C, D}                      │
└──────────────────────────────────────────────┘

Time 0:01
┌─ Node A ──────────────────────────────────────────┐
│ Send BLOCK_FOUND to:                             │
│   → Node B                                       │
│   → Node C                                       │
│   → Node D                                       │
└──────────────────────────────────────────────────┘

Time 0:02
┌─ Node B ──────────────────┐   ┌─ Node C ──────────┐
│ Receives BLOCK_FOUND      │   │ Receives BLOCK    │
│ Validates: ✅              │   │ Validates: ✅     │
│ Adds to chain             │   │ Adds to chain     │
│ Broadcasts to {A, C, D}   │   │ Broadcasts to {A,B,D}
└──────────────────────────┘   └─────────────────────┘

Time 0:03
┌─ Node D ──────────────────────────────────────┐
│ Receives BLOCK_FOUND (from B and C)           │
│ Validates: ✅                                  │
│ Adds to chain (if not already)                │
│ Broadcasts to {A, B, C}                       │
└──────────────────────────────────────────────┘

Result: All nodes have the block! 
Network is in consensus.
```

---

## How Nodes Register in Network

### Step 1: Node Startup
```python
# In pow_node.py __init__
def _register_node(self):
    """Register this node in the database"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO nodes 
        (node_id, host, port, node_type, status)
        VALUES (?, ?, ?, ?, 'active')
    ''', (self.node_id, self.host, self.port, 'full-node'))
    
    conn.commit()
    conn.close()
```

**Result in DB**:
```
nodes table:
| node_id     | host      | port  | status |
|-------------|-----------|-------|--------|
| PoW_Node_1  | 127.0.0.1 | 11111 | active |
| PoW_Node_2  | 127.0.0.1 | 22222 | active |
```

### Step 2: Peer Discovery
```python
# Each node discovers others
node.discover_nodes()
# Queries: SELECT * FROM nodes WHERE status='active'
# Result: known_nodes = {PoW_Node_2: (127.0.0.1, 22222), ...}
```

### Step 3: Network Connection
```
Node 1 ←→ Node 2
   ↕      ↕
Node 3 ←→ Node 4
```

Each node connects to all others = **Fully Connected Mesh Topology**

---

## Ledger Storage

### When Information is Stored

#### Blocks Table
```sql
INSERT INTO blocks (block_hash, previous_hash, nonce, miner_id, difficulty, data)
VALUES (?, ?, ?, ?, ?, ?)
```

**When**:
- Every time a block is mined
- Every time a block is validated and added to chain

**Example**:
```
blocks table:
| block_hash                          | miner_id    | nonce | difficulty | timestamp |
|-------------------------------------|-------------|-------|------------|-----------|
| 00abcd123...                        | PoW_Node_1  | 247   | 2          | 2024-01.. |
| 00ef4567...                         | PoW_Node_2  | 891   | 2          | 2024-01.. |
```

#### Transactions Table
```sql
INSERT INTO transactions 
(tx_hash, from_user, to_user, amount, block_id, status)
VALUES (?, ?, ?, ?, ?, ?)
```

**When**:
- Transaction is submitted
- Transaction is included in block (status='committed')

**Example**:
```
transactions table:
| tx_hash | from_user | to_user | amount | status    |
|---------|-----------|---------|--------|-----------|
| tx_123  | alice     | bob     | 100    | committed |
| tx_124  | bob       | charlie | 50     | pending   |
```

---

## Monitoring Gossip Protocol

### Check Node Discovery
```python
# In node.py
print(node.known_nodes)
# Output: {'PoW_Node_2': ('127.0.0.1', 22222), 'PoW_Node_3': ('127.0.0.1', 33333)}

print(node.get_peer_count())
# Output: 4
```

### Check Broadcasts
```
Console logs:
[PoW_Node_1] 📤 Broadcast to PoW_Node_2
[PoW_Node_1] 📤 Broadcast to PoW_Node_3
[PoW_Node_1] 📤 Broadcast to PoW_Node_4
```

### Check Message Reception
```
Console logs:
[PoW_Node_2] 📥 Message from PoW_Node_1: BLOCK_FOUND
[PoW_Node_2] ✅ Block validation passed
[PoW_Node_2] ✅ Block added to chain
```

### Query Database
```python
import sqlite3
conn = sqlite3.connect('database.sqlite3')
cursor = conn.cursor()

# Check nodes
cursor.execute('SELECT * FROM nodes WHERE status="active"')
print(cursor.fetchall())

# Check blocks
cursor.execute('SELECT count(*) FROM blocks')
print(f"Total blocks: {cursor.fetchone()[0]}")

# Check transactions
cursor.execute('SELECT * FROM transactions LIMIT 5')
print(cursor.fetchall())
```

---

## Performance Metrics

### Gossip Speed
- **Best case**: Block reaches all N nodes in log(N) hops
- **For 5 nodes**: ~2-3 hops (milliseconds)
- **For 100 nodes**: ~7 hops (seconds)

### Network Usage
- **Block size**: ~1KB
- **Broadcast cost**: 5 copies for 5 nodes = 5KB
- **Scales**: O(N) per block (linear with node count)

### Consensus Latency
- **PoW Block Time**: Depends on difficulty (seconds to minutes)
- **Gossip Propagation**: Milliseconds
- **Total Latency**: Dominated by mining/signing time

---

## Enhancement Opportunities

### 1. Selective Broadcasting (Not Implemented)
```python
# Could optimize to not send back to sender
def broadcast_block(self, block, exclude_node=None):
    for node_id, (host, port) in self.known_nodes.items():
        if node_id == exclude_node:
            continue  # Don't send back
        # ... send block
```

### 2. Peer Rotation
```python
# Could limit peers to random subset
import random
peers_to_notify = random.sample(self.known_nodes.items(), min(3, len(self.known_nodes)))
```

### 3. Message Deduplication
```python
# Track seen message hashes to avoid re-processing
self.seen_hashes = set()
message_hash = hashlib.md5(json.dumps(message).encode()).hexdigest()
if message_hash in self.seen_hashes:
    return  # Already processed
```

---

## Summary

**Aurex Gossip Protocol**:
- ✅ Node discovery via database queries
- ✅ Peer broadcasting via TCP sockets
- ✅ Message routing based on type
- ✅ Automatic ledger storage
- ✅ Fully connected mesh topology
- ✅ Gossip message propagation

**Key Files**:
- `pow_node.py` - Discovery & broadcast
- `manager_pow.py` - Message reception & routing
- `db_init.py` - Ledger storage schema
- `run_blockchain.py` - System orchestration

**Testing**:
```bash
python run_blockchain.py
# System auto-discovers nodes, broadcasts blocks, stores in ledger
```

