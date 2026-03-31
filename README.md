# Aurex — Blockchain Image Ownership Marketplace

Aurex is a Python-native marketplace where users upload images, sell them, and cryptographically prove ownership. Every upload and purchase is signed with an Ed25519 private key (stored only on the user's device) and anchored to a local Proof-of-Work blockchain.

---

## Architecture Overview

```
┌──────────────────────────────────────────────┐
│               Flet Desktop Client            │
│  login / signup / marketplace / upload /     │
│  settings (wallet key gen & backup)          │
└──────────────┬───────────────────────────────┘
               │ TLS TCP (binary framed, 4-byte prefix)
               ▼
┌──────────────────────────────────────────────┐
│           Marketplace Server                 │
│  Server/server_module.py                     │
│  • Auth, upload, buy, asset listing          │
│  • Verifies Ed25519 signature on every write │
│  • Stores assets under assets/uploads/       │
│  • SQLite: DB/marketplace.db                 │
└──────────────┬───────────────────────────────┘
               │ TCP JSON (submit_transaction / block_confirmation)
               ▼
┌──────────────────────────────────────────────┐
│           Blockchain Gateway                 │
│  blockchain/gateway_server.py  (port 5000)   │
│  • Re-verifies Ed25519 signature             │
│  • Broadcasts NEW_TRANSACTION to all nodes   │
│  • Receives block_confirmation from winner   │
│  • Writes confirmed blocks/txs/assets to DB  │
└──────────────┬───────────────────────────────┘
               │ raw JSON TCP
     ┌─────────┼─────────┐
     ▼         ▼         ▼
  Node       Node      Node   ...
 13245      13246     13247
  PoW        PoW       PoW
  Race       Race      Race
  └─ BLOCKCHAIN_DB/node_13245/ledger.json
             └─ BLOCKCHAIN_DB/node_13246/ledger.json
                        └─ BLOCKCHAIN_DB/node_13247/ledger.json
```

---

## Key Design Decisions

- **No Google Drive.** Assets are stored locally under `assets/uploads/{username}/{filename}` on the server machine.
- **No private keys on the server.** The server stores only the user's Ed25519 **public key** (in `DB/marketplace.db → wallets` table). The private key lives exclusively in `~/.aurex_wallet/aurex_private_key.pem` on the user's device.
- **Sign-and-verify on every write.** Uploads, purchases, and transfers include a signature over a canonical JSON payload. Both the marketplace server and the blockchain gateway independently verify the signature before committing anything.
- **Per-node JSON ledgers.** Each PoW node maintains its own ledger at `blockchain/BLOCKCHAIN_DB/node_{port}/ledger.json`. There is no shared ledger file between nodes.
- **SQLite only.** One database file: `DB/marketplace.db`. No external databases.

---

## Database Schema (`DB/marketplace.db`)

| Table | Purpose |
|---|---|
| `users` | Auth, email verification, wallet balance, cached public key |
| `wallets` | Ed25519 public keys — one row per user, `key_type = 'ED25519'` |
| `marketplace_items` | Asset metadata: name, owner, relative file path, price, hash |
| `notifications` | In-app notifications (e.g. "your asset was purchased") |

---

## Wallet & Ownership System

Every user needs a local Ed25519 key pair before they can upload.

**Generate keys** → Settings page → *Wallet & Identity* → **Generate My Keys**

- Private key: saved to `~/.aurex_wallet/aurex_private_key.pem` (chmod 600 on Unix)
- Public key: cached at `~/.aurex_wallet/aurex_public_key.txt`
- Both are shown in a backup overlay with a copyable JSON export — **save this file; loss of private key means loss of asset ownership**

**To encrypt the private key at rest**, set the environment variable before launching:
```powershell
$env:AUREX_WALLET_PASSWORD = "your-passphrase"
python main.py
```

---

## Prerequisites

- Python 3.10+
- Dependencies (marketplace server + Flet client + blockchain):

```powershell
pip install flet cryptography
```

Full list (add as needed):
```
flet
cryptography
```

---

## Running the Project

### One-command launch (all components)
```powershell
cd c:\dev\aurex
python aurex_launcher.py
```
This starts: blockchain nodes → gateway → marketplace server → Flet client, with staggered delays.

### Manual launch (component by component)

**1. Blockchain nodes**
```powershell
cd c:\dev\aurex\blockchain
python launcher.py --nodes 3 --difficulty 2
```

**2. Blockchain gateway**
```powershell
cd c:\dev\aurex\blockchain
python gateway_server.py
```

**3. Marketplace server**
```powershell
cd c:\dev\aurex\Server
python server_module.py
```

**4. Flet client**
```powershell
cd c:\dev\aurex
python main.py
```

---

## Network Ports

| Component | Port | Protocol |
|---|---|---|
| Marketplace server | 23456 | TLS TCP (binary framed) |
| Server discovery | 12345 | UDP broadcast |
| Blockchain gateway | 5000 | TCP JSON |
| PoW nodes | 13245–13249 | TCP JSON (P2P gossip) |
| Server notify (from gateway) | 23457 | TCP JSON |

---

## Upload & Purchase Flow

1. Open the Flet client and log in (or sign up).
2. Go to **Settings → Wallet & Identity** and generate your Ed25519 key pair. Save the backup JSON.
3. Go to **Upload Asset** — fill in name, description, price, and pick a JPG/PNG.
4. Click **Upload Asset**:
   - Client signs the asset hash + metadata with your private key.
   - Server verifies the signature, stores the file under `assets/uploads/{username}/`, and records metadata in `marketplace_items`.
   - Server queues a `mint` transaction to the blockchain gateway.
   - Gateway re-verifies the signature and broadcasts `NEW_TRANSACTION` to all PoW nodes.
   - The winning node mines a block and sends `block_confirmation` to the gateway.
   - Gateway writes the confirmed block to `marketplace.db` (blocks/transactions/assets tables).
   - Each node saves the block to its own `BLOCKCHAIN_DB/node_{port}/ledger.json`.
5. Other users see the asset in the **Marketplace**.
6. A buyer clicks **View → Buy** — same sign-and-verify cycle runs for the purchase transaction.
7. The seller receives an in-app notification when their asset is purchased.

---

## Configuration

### Server IP (if not on localhost)
```powershell
$env:AUREX_SERVER_IP = "192.168.1.50"
```
Or set it in-app via **Settings → Server Connection**.

### Wallet directory (optional override)
```powershell
$env:AUREX_WALLET_DIR = "D:\my_keys"
```

### TLS certificates
Certs are loaded from `Server/cert.pem` and `Server/key.pem`. Replace these with your own for production.

---

## Project Structure

```
aurex/
├── Client/               # Flet desktop client
│   ├── app.py            # App entry, routing, session management
│   ├── marketplace.py    # Marketplace view + full-screen asset detail
│   ├── upload.py         # Upload view (gated: requires wallet keys)
│   ├── settings.py       # Settings: wallet keygen, server config, logout
│   ├── login.py / signup.py / forgot.py
│   ├── wallet.py         # Ed25519 keygen, PEM storage, sign/verify
│   ├── protocol_client.py# Binary-framed TLS TCP client
│   ├── session.py        # UserSession, UserData
│   ├── models.py         # MarketplaceItem, ItemOffering, etc.
│   └── theme.py          # Color constants
├── Server/
│   ├── server_module.py  # Marketplace TCP server (auth, upload, buy)
│   └── DB_ORM.py         # SQLite ORM (users, wallets, items, notifications)
├── blockchain/
│   ├── gateway_server.py # Gateway: signature verify + node broadcast
│   ├── pow_node.py       # PoW node: mining, P2P gossip, per-node ledger
│   ├── launcher.py       # Spawns N PoW nodes
│   ├── classes.py        # Block, Transaction, Ledger (JSON), Notification
│   ├── config.py         # Ports, difficulty, timeouts
│   ├── key_manager.py    # Node Ed25519 key management
│   └── BLOCKCHAIN_DB/
│       ├── node_13245/ledger.json
│       ├── node_13246/ledger.json
│       └── ...
├── DB/
│   └── marketplace.db    # Single SQLite database
├── assets/
│   └── uploads/          # Uploaded files: {username}/{filename}
├── main.py               # Flet app entry point
└── aurex_launcher.py     # One-command orchestrator
```

---

## License

Private/internal project. All rights reserved.
