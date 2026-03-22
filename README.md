# Aurex — Blockchain Image Ownership Marketplace

Aurex is a Flutter marketplace where users upload images, sell them, and transfer ownership. The system anchors ownership to a **distributed PoW ledger** using **content hashes** and **client-signed transactions**, while the marketplace database acts as a fast cache for UI and search.

**Core idea**
Ownership is tied to the image content hash (SHA‑256), not usernames or database IDs. The chain is the source of truth; the DB is a cache/index.

---

**Technologies**
- Flutter (mobile UI)
- Python (marketplace server + gateway + nodes)
- TLS sockets (client ↔ server; gateway ↔ nodes)
- PoW blockchain network with allowlisted miners
- Ed25519 client signatures
- SHA‑256 content hashing
- SQLite (marketplace + internal metadata)
- Google Drive storage (image hosting)

---

**System Components**
1. **Mobile App (Flutter)**
   - Uploads assets
   - Signs blockchain transactions locally
   - Shows marketplace, wallet, notifications, ownership history

2. **Marketplace Server (Python)**
   - Auth, wallet, listings, notifications
   - Validates signatures and timestamps
   - Submits txs to Gateway
   - Listens for block confirmations

3. **Gateway (Python)**
   - Entry point for transactions
   - Replay protection and signature verification
   - Broadcasts to nodes

4. **PoW Nodes (Python)**
   - Mine transactions
   - Validate signatures + PoW + allowlist
   - Persist per‑node ledger

---

**Ownership Model (No DB Trust)**
The asset identity is the SHA‑256 hash of the image file. This hash is recorded on-chain.

- **Chain is authoritative**
- **DB is index/cache**
- If the DB is lost, ownership can be rebuilt by replaying the chain

---

**Workflows**

**Upload + Mint**
```text
User (Flutter)
  -> SHA-256 hash of image
  -> Sign mint payload (Ed25519)
  -> Upload chunks
Server
  -> Verify signature + hash
  -> Upload to Google Drive
  -> Save to DB
  -> Submit mint tx to Gateway
Gateway
  -> Verify signature + replay protection
  -> Broadcast to nodes
Nodes
  -> PoW mine + validate
  -> Block confirmation -> Server
```

**Purchase**
```text
Buyer (Flutter)
  -> Sign purchase payload (tx_id + asset_hash + price)
Server
  -> Verify signature + wallet + ownership
  -> Submit purchase tx to Gateway
Gateway
  -> Verify signature + replay protection
Nodes
  -> Mine and confirm
Server
  -> Update wallet + ownership
  -> Notify buyer & seller
```

**Transfer**
```text
Sender (Flutter)
  -> Sign transfer payload (tx_id + asset_hash)
Server -> Gateway -> Nodes -> Server
```

---

**Security Model**
- **Client‑signed transactions:** Ed25519 signatures generated on device.
- **Content hash anchoring:** SHA‑256 hash stored on chain.
- **Replay protection:** `tx_id` uniqueness + timestamp windows.
- **Permissioned miners:** optional allowlist of miner public keys.
- **TLS sockets** for client ↔ server.

---

**Ledger Storage**
Each node maintains its **own ledger file**:
```text
blockchain/BLOCKCHAIN_DB/ledger_node_<port>.pickle
```

---

**Run It**
1. Start nodes
```powershell
cd c:\dev\aurex\blockchain
python launcher.py --nodes 3 --difficulty 2
```

2. Start gateway
```powershell
cd c:\dev\aurex\blockchain
python gateway_server.py
```

3. Start marketplace server
```powershell
cd c:\dev\aurex
python python_files\server_moudle.py
```

4. Run Flutter app
```powershell
cd c:\dev\aurex
flutter run
```

---

**Configuration Notes**
- `python_files/config.py` controls server ports and Google Drive setup.
- `blockchain/config.py` controls node ports, difficulty, replay windows, allowlist.
  
Allowlist helper:
```powershell
cd c:\dev\aurex\blockchain
python print_key_fingerprints.py
```
Copy the printed fingerprints into `blockchain/config.py` and set `ENFORCE_MINER_ALLOWLIST = True`.

---

**Design Completeness (95% → 100%)**
Recommended final polish:
1. **Push notifications** via FCM/APNs (app‑closed delivery).
2. **Key export/backup UI** with secure storage.
3. **Chain viewer screen** for on‑device audit trail.
4. **Fork handling strategy** (longest chain or cumulative difficulty).
5. **Rate limiting** on gateway and server.

---

**License**
Private/internal project. All rights reserved.
