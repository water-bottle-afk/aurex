# Aurex Blockchain - Quick Start Guide

## 🚀 5-Minute Setup

### Prerequisites
```bash
# Make sure you have Python 3.8+
python --version

# Navigate to blockchain directory
cd c:\dev\aurex\blockchain
```

### Run the Full System

```bash
python run_blockchain.py
```

That's it! This will:
1. ✅ Initialize SQLite database
2. ✅ Create 3 PoW nodes + 2 PoA nodes
3. ✅ Auto-connect nodes in P2P mesh
4. ✅ Send 5 test transactions
5. ✅ Display network status
6. ✅ Show blockchain state
7. ✅ Open interactive monitoring

---

## 📊 What You'll See

### Startup Output
```
======================================================================
    AUREX BLOCKCHAIN SYSTEM MANAGER
======================================================================

Configuration:
  • PoW Nodes:     3
  • PoA Nodes:     2
  • PoW Difficulty: 2 (leading zeros)

======================================================================
🗄️  STEP 1: INITIALIZING DATABASE
======================================================================

✅ Database tables created:
   • users
   • nodes
   • blocks
   • transactions
   • assets
   • mining_pool
```

### Mining Progress
```
⛏️ [PoW_Node_1] MINING STARTED
   Target: 00... (2 leading zeros)
   Data: Asset_Creation_2024-01-14T10...
   Previous Hash: 0000000000000000...

   [PoW_Node_1] Nonce:      50000 | Hash: 1234abcd... | Rate:   45000 H/s
   [PoW_Node_1] Nonce:     100000 | Hash: 5678efgh... | Rate:   47000 H/s

✅ [PoW_Node_1] BLOCK FOUND!
   Hash: 00abcd123456789...
   Nonce: 247
   Time: 2.15s
   Hash/sec: 114
   Attempts: 247

   [DB] Block stored: 00abcd123456...
```

### Block Propagation
```
[PoW_Node_2] 📥 Received BLOCK_FOUND from PoW_Node_1
[PoW_Node_2] 🔗 Processing block: 00abcd12...
[PoW_Node_2] ✅ Block validation passed
[PoW_Node_2] ✅ Block added to chain
[PoW_Node_2] 📡 Block broadcasted to peers
```

### Interactive Mode
```
======================================================================
🎮 INTERACTIVE MODE - System Running
======================================================================

Commands:
  status   - Show network status
  chain    - Show blockchain state
  ledger   - Show database ledger
  tx <msg> - Send transaction with message
  quit     - Stop system

blockchain> status

======================================================================
📊 NETWORK STATUS REPORT
======================================================================

[PoW_Node_1] Status: RUNNING | Peers: 4 | Blocks: 5
[PoW_Node_2] Status: RUNNING | Peers: 4 | Blocks: 5
[PoW_Node_3] Status: RUNNING | Peers: 4 | Blocks: 5
[PoA_Node_1] Status: RUNNING | Peers: 4 | Blocks: 3
[PoA_Node_2] Status: RUNNING | Peers: 4 | Blocks: 3

blockchain> ledger

======================================================================
📖 BLOCKCHAIN LEDGER (DATABASE)
======================================================================

🔷 BLOCKS: 5 total
   • Hash: 00abcd123456... | Miner: PoW_Node_1        | Difficulty: 2
   • Hash: 00ef4567890a... | Miner: PoW_Node_2        | Difficulty: 2
   ...

💳 TRANSACTIONS: 5 total
   • alice@example.com      → bob@example.com          [committed]
   • bob@example.com        → charlie@example.com      [pending]
   ...

🔗 ACTIVE NODES: 5 total
```

---

## 🎮 Interactive Commands

### 1. Check Status
```
blockchain> status
```
Shows:
- Node status (RUNNING/STOPPED)
- Number of connected peers
- Number of blocks each node has

### 2. View Blockchain
```
blockchain> chain
```
Shows:
- Full blockchain from each node
- Block index, hash, timestamp, data

### 3. Query Ledger
```
blockchain> ledger
```
Shows:
- All blocks in database
- All transactions with status
- List of active nodes

### 4. Send Transaction
```
blockchain> tx Transfer 100 coins from Alice to Bob
```
This will:
1. Create transaction message
2. Send from PoW_Node_1 to network
3. Broadcast via gossip protocol
4. Include in next mined block
5. Store in transactions table

### 5. Exit
```
blockchain> quit
```
Gracefully stops all nodes

---

## 📝 Common Scenarios

### Scenario 1: Watch Mining
```
1. Run: python run_blockchain.py
2. Watch console for mining progress
3. See blocks being mined every ~2 seconds
4. See blocks propagating to other nodes
```

### Scenario 2: Send Transaction
```
blockchain> tx User Registration alice@example.com
blockchain> tx User Registration bob@example.com
blockchain> tx Transfer 50 coins alice to bob

# View in ledger:
blockchain> ledger
```

### Scenario 3: Monitor Network
```
blockchain> status    # Check all nodes
blockchain> chain     # View all blockchains
blockchain> ledger    # Check database state
```

### Scenario 4: Test Resilience
Kill one node and see others continue:
```
1. Run system
2. Send transactions
3. In another terminal: Find process and kill
4. See other nodes continue mining
5. Blockchain continues to grow
```

---

## 🔧 Advanced Options

### Custom Node Count
```bash
# 5 PoW nodes, 3 PoA nodes, difficulty 3
python run_blockchain.py --pow 5 --poa 3 --difficulty 3
```

### Custom Difficulty
```bash
# Higher difficulty = harder mining = slower blocks
python run_blockchain.py --difficulty 3

# Lower difficulty = easier mining = faster blocks
python run_blockchain.py --difficulty 1
```

---

## 📊 Understanding the Output

### Mining Output
```
Nonce: 247        ← Current attempt number
Hash: 00f2...     ← Current hash being tested
Rate: 114 H/s     ← Hashes per second (speed)
Time: 2.15s       ← Time to find solution
Attempts: 247     ← Total attempts needed
```

### Block Validation
```
✅ Block validation passed    ← Hash meets difficulty
❌ Block validation failed    ← Doesn't have enough leading zeros
```

### Peer Broadcasting
```
📡 Block broadcasted to peers  ← Sent to 4/5 peers
✅ Block added to chain        ← Stored locally
📥 Message from PoW_Node_1    ← Received from peer
```

---

## 🐛 Troubleshooting

### Port Already in Use
```
Error: [Errno 48] Address already in use
```
**Fix**: Change difficulty or ports, or kill old process

### Database Locked
```
Error: database is locked
```
**Fix**: Remove `database.sqlite3` to reset

### No Blocks Being Mined
```
Check:
1. blockchain> status    (is system running?)
2. Difficulty is reasonable (start with 2)
3. Look for error messages in console
```

### Peers Not Connected
```
Check:
1. blockchain> status    (should show Peers: 4)
2. All nodes should have same peer count
3. Try restarting system
```

---

## 📚 Documentation Files

| File | Purpose |
|------|---------|
| `BLOCKCHAIN_SYSTEM.md` | Complete system documentation |
| `GOSSIP_PROTOCOL.md` | How P2P gossip works |
| `QUICK_START.md` | This file |
| `config.py` | Configuration constants |
| `run_blockchain.py` | Main entry point |

---

## 🎯 Next Steps

1. **Start the system**
   ```bash
   python run_blockchain.py
   ```

2. **Send test transactions**
   ```
   blockchain> tx Create new asset NFT_001
   blockchain> tx Register user alice@example.com
   ```

3. **Monitor the ledger**
   ```
   blockchain> ledger
   ```

4. **Explore the code**
   - `pow_node.py` - PoW mining logic
   - `p2p_engine.py` - P2P networking
   - `manager_pow.py` - Consensus management

5. **Scale up**
   ```bash
   python run_blockchain.py --pow 10 --poa 5
   ```

---

## ✅ Success Indicators

You'll know everything is working when:

- ✅ Database initializes (no errors)
- ✅ 5 nodes start (3 PoW + 2 PoA)
- ✅ Nodes connect to each other (Peers: 4)
- ✅ Blocks are mined (see "BLOCK FOUND")
- ✅ Blocks propagate (see 📥 messages)
- ✅ Ledger shows transactions
- ✅ Interactive commands work

---

## 💾 Ledger Persistence

All data is stored in SQLite:
```
c:\dev\aurex\blockchain\database.sqlite3
```

Tables:
- `blocks` - All mined blocks
- `transactions` - All transactions
- `nodes` - Network node registry
- `assets` - Digital assets
- `users` - User accounts

Query the ledger directly:
```python
import sqlite3
conn = sqlite3.connect('c:/dev/aurex/blockchain/database.sqlite3')
cursor = conn.cursor()
cursor.execute('SELECT * FROM blocks LIMIT 10')
for row in cursor:
    print(row)
```

---

## 📞 Getting Help

**Check logs**:
```bash
# Look for blockchain.log if configured
tail -f blockchain.log
```

**Run with more nodes**:
```bash
python run_blockchain.py --pow 5 --poa 3
```

**Use interactive mode**:
```
blockchain> status     # Check everything
blockchain> ledger     # Verify data stored
blockchain> chain      # Verify consensus
```

**Review documentation**:
- See `BLOCKCHAIN_SYSTEM.md` for architecture
- See `GOSSIP_PROTOCOL.md` for networking details

---

## 🎉 You're Ready!

Your blockchain system is ready to:
- ✅ Mine blocks with PoW
- ✅ Validate with PoA
- ✅ Propagate blocks via gossip
- ✅ Store in persistent ledger
- ✅ Handle multiple transactions
- ✅ Scale to many nodes

**Start now**: `python run_blockchain.py`

