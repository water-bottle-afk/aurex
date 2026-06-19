# Aurex — Blockchain Digital Marketplace

Aurex is a fully self-contained, peer-to-peer digital asset marketplace built on a custom proof-of-work blockchain. Users upload image assets, cryptographically sign them with ECDSA secp256k1 wallets, and the network mines them into an immutable ledger. Every ownership transfer, listing, and de-listing is recorded as a signed on-chain transaction. No external blockchain library is used — the chain, the mining loop, the consensus, and the peer sync are all written from scratch in Python.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Component Reference](#component-reference)
3. [Startup](#startup)
4. [Protocol Reference](#protocol-reference)
5. [Asset Lifecycle](#asset-lifecycle)
6. [Blockchain — Bnode](#blockchain--bnode)
7. [Gateway](#gateway)
8. [Server & ORM](#server--orm)
9. [Client — UI, Cache, Wallet](#client--ui-cache-wallet)
10. [Shared Resources](#shared-resources)
11. [Security Model](#security-model)
12. [Python Engineering Highlights](#python-engineering-highlights)
13. [Directory Layout](#directory-layout)

---

## Architecture Overview

Aurex uses a **four-tier star topology**. The client never touches the blockchain directly — everything flows through the server and gateway.

```
┌─────────────────────────────────────────────────────────────────────┐
│                           AUREX NETWORK                             │
│                                                                     │
│  [Client]  ←──AES/RSA──►  [Server]  ←──AES/RSA──►  [Gateway]      │
│   Flet UI                  Auth/ORM                  Relay/Validator│
│   Wallet                   Push events               Block verifier │
│   ImageCache               Asset storage             PoW router     │
│                                  │                        │         │
│                                  └────────────────────────┘         │
│                                               │                     │
│                                ┌──────────────▼──────────────┐      │
│                                │      [Blockchain Nodes]      │      │
│                                │   Bnode × N  (PoW miners)   │      │
│                                │  ledger.json + balances.json │      │
│                                └─────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

| Component | Entry Point | Role |
|-----------|-------------|------|
| **Client** | `Client/client.py` | Flet desktop UI, ECDSA wallet, per-user image cache, server protocol client |
| **Server** | `Server/server_module.py` | Authentication, JSON ORM, asset storage, push-event broker, gateway relay |
| **Gateway** | `Gateway/gateway.py` | Stateless relay between server and nodes; validates mined blocks; routes balance queries to the longest-chain node |
| **Blockchain Node (Bnode)** | `Blockchain/Bnode.py` | SHA-256 PoW mining, immutable ledger, AUR balance accounting, peer-to-peer ledger sync |

---

## Component Reference

### Client (`Client/`)

- Full Flet desktop UI — dark gold theme, seven routed pages
- RSA+AES encrypted TCP connection to the server (`Client` class wraps `RSA_Client`)
- Async receive/send queue model: a background thread routes push events into dedicated queues (`balance_queue`, `asset_sold_queue`, `notification_queue`, etc.) so the UI thread is never blocked on I/O
- ECDSA secp256k1 wallet: private key stays local; public key registered with the server on every wallet load or generate
- Per-user disk cache (`ImageCache`) — stores asset images and metadata as `{asset_id: metadata_dict}`, with balance persistence between sessions
- `ClientApp` owns all state and drives page navigation via Flet route changes; pages are pure UI and call only `app.*` methods

### Server (`Server/`)

- Listens for client and gateway TCP connections via `RSA_Server`; one thread per connected peer
- JSON-backed ORM (`DB_ORM.ORM`) — no external database; all state in three JSON files
- Handles the full client protocol: auth, upload pipeline (INIT → UPLOAD chunks → FINISH), marketplace actions, account management
- Acts as gateway bridge: forwards blockchain tasks (`UPLOAD_ASSET`, `LIST_ASSET`, `TX_REQUEST_BUY`, `UNLIST_ASSET`) and pushes confirmed results back to the correct online client via `push_event()`
- Soft-delete for user accounts: credentials are wiped, `user_status` set to `DELETED`, public key preserved for historical blockchain linkage
- Assets owned by a deleted account enter `PENDING_DELETION` status; they become `DELETED` only after the blockchain settlement window closes (so a concurrent buy can still succeed)
- Password hashing: SHA-256(pepper + password + salt); 6-digit OTP reset via SMTP email

### Gateway (`Gateway/gateway.py`)

- Stateless with respect to user data — holds **no** asset records, **no** user accounts
- Maintains `gateway_ledger.json` purely for block index/prev_hash continuity checking
- Deduplicates transactions with `seen_tx_ids` (UUID set) and prevents double-minting with `seen_minted_asset_ids`
- Routes `GET_BALANCE` only to the node with the longest chain to prevent duplicate responses
- Validates mined blocks (hash integrity + PoW target) before broadcasting to peers
- Triggers ledger sync (`GET_LEDGER`) for nodes that fall behind
- Discovered by nodes via UDP broadcast (`WHRSV` → `SRVAT|<ip>|<port>`)

### Blockchain Node (`Blockchain/Bnode.py`)

- Discovers gateway via UDP broadcast; registers with `REGISTER_BLOCKCHAIN_NODE`
- Mines SHA-256 PoW blocks in a separate **daemon thread** per task — the gateway listener loop never blocks during mining
- Maintains a full `ledger.json` (immutable chain) and `balances.json` (public key → AUR) per node directory
- Peer-to-peer ledger sync: chunks the chain and streams it to lagging nodes via `LEDGER_SNAPSHOT_*` messages
- Node keys stored in `Node_keys/` (RSA key pair for peer connections)
- Stops mining immediately when `BROADCAST_TX_TO_VERIFY` arrives (another node won the race)

---

## Startup

### One-shot launcher (recommended)

```
python aurex_launcher.py [--debug-level DEBUG|INFO|WARNING|ERROR]
```

Opens four separate terminal windows in startup order:

| Window | Process |
|--------|---------|
| `Aurex-Nodes` | Blockchain node on port 14253 |
| `Aurex-Gateway` | Gateway (waits 2 s for nodes to register) |
| `Aurex-Marketplace` | Server (waits 3 s for gateway) |
| `Aurex-Client` | Flet desktop app |

### Manual order

```bash
# Terminal 1 — blockchain node
cd Blockchain
python Bnode.py --difficulty 3 --port 14253

# Terminal 2 — gateway
cd Gateway
python gateway.py

# Terminal 3 — server
cd Server
python server_module.py

# Terminal 4 — client
cd Client
python client.py
```

**First-time setup:** after login, go to **Settings → Wallet & Identity → Generate New Wallet** before uploading or buying assets.

---

## Protocol Reference

All messages are JSON dicts with a `"type"` field (always `UPPER_SNAKE_CASE`). Transport is RSA-2048-OAEP handshaked then AES-128-CBC encrypted for all subsequent messages.

### Client → Server

| Type | Purpose |
|------|---------|
| `LOGIN` | Authenticate (username + password) |
| `SIGNUP` | Register new account (username, password, email) |
| `SEND_CODE` | Request 6-digit OTP to email for password reset |
| `VERIFY_CODE` | Submit OTP; server confirms before allowing reset |
| `UPDATE_PASSWORD` | Set new password (requires valid OTP) |
| `UPDATE_PUBLIC_KEY` | Register or replace ECDSA wallet public key |
| `UPLOAD_INIT` | Begin chunked upload (metadata + client-generated `upload_id`) |
| `UPLOAD` | Send one base64-encoded file chunk |
| `UPLOAD_FINISH` | Finalise upload; receive `asset_id` |
| `MOVE_TO_MARKETPLACE` | Trigger PoW mining to list an asset (`PENDING`→MINT or `UNLISTED`→LIST) |
| `GET_ASSETS_IDS` | List `{id, version}` entries — marketplace (no username) or owned (with username) |
| `GET_ASSET_BY_ID` | Streaming asset download (metadata + chunked image) |
| `BUY_ASSET` | Submit signed buy transaction |
| `UNLIST_ASSET` | Remove an asset from the marketplace via PoW |
| `DELETE_ASSET` | Delete own asset from DB and disk immediately |
| `GET_BALANCE` | Request fresh AUR balance from blockchain |
| `LOGOUT` | End session |
| `DELETE_ACCOUNT` | Soft-delete account; freeze all assets in PENDING_DELETION |

### Server → Client (push events)

Arrive asynchronously on the persistent connection. The client routes them by type into dedicated queues — they never enter the request/response queue.

| Type | Meaning |
|------|---------|
| `BALANCE_IS` | Updated AUR balance from the blockchain |
| `FULLY_UPLOADED` | Asset mined and now `FOR_SALE` on the marketplace |
| `ASSET_LISTED` | Alias for `FULLY_UPLOADED` (re-list path) |
| `ASSET_UNLISTED` | Asset removed from marketplace (sent to asset owner) |
| `ASSET_REMOVED` | Asset no longer visible on marketplace (broadcast to all users) |
| `ASSET_SOLD` | Owner's asset was purchased (sent to seller) |
| `BUY_SUCCESS` | Trade settled on-chain (sent to buyer) |
| `BUY_FAILED` | Transaction rejected — duplicate, insufficient balance, or race loss |
| `BLOCK_ACCEPTED` | Sell block confirmed |
| `BLOCK_REJECTED` | Block rejected by nodes |
| `NOTIFICATION` | General server notification string |
| `HIDE_ASSETS_OF_USER` | Silently remove a deleted user's assets from marketplace grids |

### Server ↔ Gateway

| Type | Direction | Purpose |
|------|-----------|---------|
| `REGISTER_GATEWAY` | G→S | Gateway announces itself on startup |
| `CREATE_BALANCE` | S→G→Nodes | Create initial 100 AUR balance for a new wallet |
| `UPLOAD_ASSET` | S→G→Nodes | Mint a new asset (PENDING) — triggers `ASSET_MINT` PoW |
| `LIST_ASSET` | S→G→Nodes | Re-list an unlisted asset — triggers `LIST_ASSET` PoW |
| `UNLIST_ASSET` | S→G→Nodes | Remove asset from marketplace — triggers `UNLIST_ASSET_FROM_BLOCKCHAIN` PoW |
| `TX_REQUEST_BUY` | S→G→Nodes | Buy transaction — triggers `BUY` PoW |
| `GET_BALANCE` | S→G→Node | Request AUR balance (routed to longest-chain node only) |
| `SEND_BALANCE` | Nodes→G→S | Balance response from winning node |
| `BUY_SUCCESS` | Nodes→G→S | Confirmed buy block |
| `FULLY_UPLOAD` | G→S | Validated MINT/LIST block; mark asset `FOR_SALE` |
| `ASSET_UNLISTED` | G→S | Validated UNLIST block; mark asset `UNLISTED` |
| `BROADCAST_TX_TO_VERIFY` | G→Nodes | Winning block; all other nodes stop mining and apply it |

### Node ↔ Node (peer sync)

| Type | Purpose |
|------|---------|
| `GET_LEDGER` | Request chain from a peer that is ahead |
| `LEDGER_SNAPSHOT_BEGIN` | Start of chunked chain transfer |
| `LEDGER_SNAPSHOT_CHUNK` | One chunk of serialised ledger blocks |
| `LEDGER_SNAPSHOT_END` | End of transfer |

---

## Asset Lifecycle

```
            ┌─────────┐
            │ PENDING │  ← uploaded, image saved to disk, not yet on-chain
            └────┬────┘
                 │ MOVE_TO_MARKETPLACE  (first listing)
                 │ → server sends UPLOAD_ASSET to gateway
                 │ → nodes mine ASSET_MINT tx
                 ▼
           ┌──────────┐
           │ FOR_SALE │  ← on-chain, visible in the marketplace
           └────┬─────┘
        ┌───────┼───────────────┐
        │       │               │
  UNLIST_ASSET  │           BUY_ASSET
  → UNLIST PoW  │           → BUY PoW mined
        │       │           → ownership transferred
        ▼       │           → seller: ASSET_SOLD push
  ┌──────────┐  │           → buyer: BUY_SUCCESS push
  │ UNLISTED │  │           → all: ASSET_REMOVED push
  └────┬─────┘  │
       │ MOVE_TO_MARKETPLACE  (re-list)
       │ → server sends LIST_ASSET to gateway
       │ → nodes mine LIST_ASSET tx  (no re-mint)
       ▼
  ┌──────────┐
  │ FOR_SALE │  ← back on the marketplace
  └──────────┘

  Account deletion path:
  any status → PENDING_DELETION  (freeze, remove from grids)
             → DELETED           (after blockchain settlement window)
             (if bought during window: ownership transfers, blockchain wins)
```

Transaction types written to the blockchain:

| `tx_type` | Triggered by | AUR transfer |
|-----------|--------------|--------------|
| `ASSET_MINT` | `MOVE_TO_MARKETPLACE` (first time) | 0 AUR |
| `LIST_ASSET` | `MOVE_TO_MARKETPLACE` (re-list) | 0 AUR |
| `UNLIST_ASSET_FROM_BLOCKCHAIN` | `UNLIST_ASSET` | 0 AUR |
| `BUY` | `BUY_ASSET` | price AUR (buyer → seller) |

---

## Blockchain — Bnode

### Proof of Work

```python
while True:
    block_json = json.dumps(block, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(block_json).hexdigest()
    if digest.startswith("0" * difficulty):
        block["hash"] = digest
        break
    block["nonce"] += 1
```

Difficulty is set in `SharedResources/config.py` (`POW_DIFFICULTY = 3` by default).

### Block structure

```json
{
  "index": 12,
  "prev_hash": "000abc...",
  "timestamp": "2026-06-07T14:30:00.000000",
  "tx": {
    "tx_type": "ASSET_MINT",
    "tx_id": "a3f1...",
    "asset_id": "de987ea8...",
    "owner_username": "alice",
    "sender": "04ab...ff",
    "receiver": "",
    "amount": 0.0,
    "signature": "3045...",
    "public_key": "04ab...ff",
    "timestamp": "2026-06-07T14:29:58.000000",
    "img_hash": "sha256-of-file"
  },
  "nonce": 4821,
  "difficulty": 3,
  "hash": "000fa3..."
}
```

### Local storage per node

```
Blockchain/node_<ip>_<port>/
    ledger.json        ← full immutable chain
    balances.json      ← { "04ab...ff": 75.0, ... }
    Node_keys/         ← RSA key pair for peer handshakes
```

### Double-mint guard (two layers)

1. **Gateway layer** — `seen_minted_asset_ids` (populated from `gateway_ledger.json` on startup) rejects any `UPLOAD_ASSET` request whose `asset_id` was already minted. Also deduplicates incoming mined blocks by `tx_id`.
2. **Node layer** — `handle_mint_request` scans `self.chain` before mining; if the `asset_id` already has an `ASSET_MINT` block, the node skips silently.

### Mining concurrency model

Each mining task runs in a **daemon thread** (`threading.Thread(..., daemon=True)`). The gateway listener loop continues to receive new messages while mining is in progress. When `BROADCAST_TX_TO_VERIFY` arrives (another node won), the thread's `mine()` method exits early via a threading `Event` stop flag.

---

## Gateway

The gateway is **stateless with respect to user data** — it never reads or writes the asset database or user accounts. Its only persisted state is `gateway_ledger.json` (a mirror of mined blocks used for block validation and deduplication continuity across restarts).

| Responsibility | Mechanism |
|---------------|-----------|
| TX deduplication | `seen_tx_ids: set[str]` — UUID set, per-session |
| Mint deduplication | `seen_minted_asset_ids: set[str]` — loaded from ledger on startup |
| Block validation | Hash integrity + PoW target check in `verify_mined_block()` |
| Balance routing | `best_node_addr()` — routes `GET_BALANCE` to the node with the longest chain |
| Lagging node sync | Sends `GET_LEDGER` to any node whose chain length falls behind |
| Node discovery | UDP `UDPServer` replies `SRVAT|<ip>|<port>` to `WHRSV` broadcasts |

---

## Server & ORM

### JSON ORM (`Server/DB_ORM.py`)

No external database. All persistence is thread-safe JSON file I/O protected by `threading.RLock()`.

| File | Schema |
|------|--------|
| `DB/users.json` | `{ username → user_dict }` — email, salt, password hash, public key, OTP fields, `user_status` |
| `DB/marketplace_items.json` | `{ asset_id → asset_dict }` — O(1) lookup; `storage_path` stored relative to `DB/` |
| `DB/notifications.json` | `{ username → [{ msg }] }` — pending push notifications for offline users |
| `DB/uploads/<username>/` | Sanitised uploaded image files, named `<sha256_hash>.<ext>` |
| `DB/pepper.txt` | Global pepper loaded once at startup; never stored alongside the hash |

`marketplace_items.json` asset entry format (mirrors the client-side `metadata.json`):

```json
{
  "de987ea8f1bc4a12": {
    "asset_id":     "de987ea8f1bc4a12",
    "owner":        "alice",
    "asset_name":   "Golden Gate",
    "description":  "Photo of the bridge",
    "file_type":    "jpg",
    "cost":         50.0,
    "created_at":   "2026-06-19T10:00:00.000000",
    "version":      2,
    "asset_status": "FOR_SALE",
    "public_key":   "04ab...ff",
    "storage_path": "uploads/alice/de987...jpg"
  }
}
```

Key ORM methods:

| Method | Purpose |
|--------|---------|
| `add_user(username, password, email)` | Register user; rejects duplicate username/email |
| `get_user(username)` | Fetch `User` object by username |
| `soft_delete_user(username)` | Erase credentials, set `user_status=DELETED`, preserve `public_key` |
| `get_user_by_public_key(pk)` | Reverse-lookup for blockchain event attribution |
| `add_asset(username, item)` | Insert asset keyed by `asset_id`; stores relative `storage_path` |
| `find_asset_by_id(asset_id)` | O(1) lookup by `asset_id` |
| `get_all_for_sale_assets()` | All `FOR_SALE` assets for the marketplace |
| `get_assets_for_user(username)` | User's non-FOR_SALE assets (My Assets view) |
| `update_asset_status(asset_id, status)` | Change lifecycle status; optionally increments `version` |
| `transfer_asset(asset_id, from, to)` | Atomic ownership transfer; validates status is `FOR_SALE` or `PENDING_DELETION` |
| `delete_asset(asset_id, owner)` | Hard-delete asset record and check owner match |
| `set_assets_pending_deletion(username)` | Freeze all user assets on account delete; returns affected IDs |
| `finalize_pending_deletions(exclude)` | Mark PENDING_DELETION assets as DELETED after blockchain window |
| `queue_notification(username, msg)` | Persist notification for an offline user |
| `flush_notifications(username)` | Return and clear all queued notifications |

### Password hashing

```
hash = SHA-256( pepper + plaintext_password + salt )
```

- **pepper** — global secret in `DB/pepper.txt`; never stored alongside the hash
- **salt** — per-user 7-digit random string stored in `users.json`
- **OTP reset** — 6-digit code, sent via SMTP, expires after 5 minutes

### Image sanitisation

Uploaded images are re-rendered through Pillow (`PIL.Image`) before being saved to disk. The process strips all EXIF data, metadata, embedded scripts, and steganographic payloads by reconstructing a new `Image` from raw pixel data only. If Pillow is not installed, a magic-byte signature check is applied as a fallback.

---

## Client — UI, Cache, Wallet

### Pages (`Client/pages.py`)

| Route | Page |
|-------|------|
| `/login` | Sign-in form |
| `/signup` | Account registration |
| `/forgot` | Three-step password reset (email → OTP → new password) |
| `/settings` | Wallet management, account deletion danger zone |
| `/marketplace` | Browse and buy `FOR_SALE` assets; real-time grid updates via push events |
| `/upload` | Mint a new asset (upload → PENDING → mining → FOR_SALE) |
| `/my_assets` | View owned assets; re-list UNLISTED or delete PENDING assets |
| `/notifications` | History of all server push events |

### Image cache (`Client/client.py — ImageCache`)

```
Client/<username>/cache/
    metadata.json        ← { asset_id: { ...metadata, "path": "assets/<id>.<ext>" } }
    assets/
        <asset_id>.<ext> ← downloaded image bytes
```

- Assets are re-fetched from the server only when `server_version > cached_version`
- Balance is persisted to `metadata.json` on every `BALANCE_IS` push event and loaded on login so the UI shows a value instantly before the fresh blockchain query returns
- Old cache formats (flat string values, nested `meta` key) are detected and migrated or cleared automatically on startup
- The zoomed-card enlargement renders images via `src_base64` (raw bytes → base64) for compatibility across Flet versions

### Wallet (`Client/wallet_manager.py`)

ECDSA secp256k1 key pairs generated with `cryptography.hazmat.primitives.asymmetric.ec`.

```
Client/<username>/wallet.json
```

```json
{
  "username": "alice",
  "public_key": "04ab...ff",
  "private_key": "3c1f...ab"
}
```

Signing a transaction payload:

```python
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
signature = private_key.sign(canonical, ec.ECDSA(hashes.SHA256()))
```

The gateway verifies ECDSA signatures on each block before accepting. The public key is embedded in every block so nodes can verify without a separate user lookup.

### Gateway offline handling

`ClientApp` tracks `gateway_online: bool | None`:

- `None` — unknown (initial state immediately after login)
- `True` — confirmed online (any gateway-dependent operation succeeded)
- `False` — confirmed offline (server returned "Gateway Server isn't online")

When offline, a warning banner appears on the Marketplace page and buy / unlist / upload-to-marketplace actions are blocked with clear error messages. The cached AUR balance is used as a fallback when `GET_BALANCE` fails.

---

## Shared Resources

### `SharedResources/classes.py`

#### `Communication`

Wraps a TCP socket with:

- **AES-CBC encryption** — all messages encrypted after the RSA handshake
- **2-byte length framing** — `struct.pack('!H', len(msg))` prefix; supports messages up to 65 535 bytes
- **Async duplex queues** — `start_async()` spawns a recv thread (feeds `msg_queue`) and a send thread (drains `send_queue`); I/O never blocks the caller
- **Thread-safe sends** — `send_lock` (`threading.Lock`) prevents concurrent `sendall` calls interleaving bytes
- **Thread-safe recvs** — `recv_lock` (`threading.Lock`) prevents frame corruption from concurrent readers

#### `RSA_Server` / `RSA_Client`

Handshake on every new connection:

```
Client                              Server
  ──── SEND_PUBLIC_KEY ──────────►
  ◄─── GET_PUBLIC_KEY (RSA pub) ───
  ──── GET_SYMETRIC_KEY ─────────►   (AES key encrypted with RSA-OAEP)
  ◄─── OK ─────────────────────────  (all subsequent messages AES-CBC encrypted)
```

RSA keys are stored in `*Keys/` directories relative to each component and reused across restarts.

#### `UDPServer` / `UDPClient`

Simple UDP broadcast discovery: nodes broadcast `WHRSV` on the LAN; the gateway `UDPServer` replies `SRVAT|<ip>|<port>` so nodes know where to connect without hardcoded addresses.

#### Dataclasses

| Class | Fields |
|-------|--------|
| `MarketplaceItem` | `asset_id, owner, asset_name, description, file_type, cost, created_at, storage_path, version, asset_status, public_key` |
| `Transaction` | `sender, receiver, amount, signature, tx_type, tx_id, asset_id, public_key, timestamp` |
| `Block` | `index, prev_hash, timestamp, tx, nonce, difficulty, hash` |

`MarketplaceItem.from_dict()` includes a migration path for old `blockchain_status`/`for_sale` field names.

### `SharedResources/config.py`

Single source of truth for all network addresses, ports, PoW difficulty, and initial balance.

```python
SERVER_IP,  SERVER_PORT          = "10.100.102.58", 55554
GATEWAY_IP, GATEWAY_BLOCKCHAIN_PORT = "10.100.102.58", 33334
GATEWAY_UDP_PORT                 = 22222
POW_DIFFICULTY                   = 3
INITIAL_BALANCE                  = 100
```

Change it once to reconfigure the whole network.

### `SharedResources/logging.py`

ANSI-coloured console output with a configurable global level (`--debug-level` CLI flag):

| Level | Colour |
|-------|--------|
| `DEBUG` | Green |
| `INFO` | Light blue |
| `WARNING` | Orange |
| `ERROR` | Red |

---

## Security Model

| Layer | Mechanism |
|-------|-----------|
| **Transport encryption** | RSA-2048-OAEP key exchange, then AES-128-CBC for all messages |
| **Message integrity** | 2-byte length framing; JSON parse errors silently drop the message |
| **Asset ownership** | ECDSA secp256k1 signatures — every tx payload signed by the owner's private key |
| **Block integrity** | SHA-256 hash over full block dict (canonical JSON, sorted keys); PoW target enforced by gateway before broadcast |
| **Password storage** | SHA-256(pepper + password + salt) — pepper never stored with the hash |
| **OTP reset** | 6-digit random code, 5-minute expiry, verified before password change |
| **Image sanitisation** | PIL re-render strips all EXIF, metadata, and embedded payloads from uploads |
| **Double-mint prevention** | Two layers: gateway `seen_minted_asset_ids` set + per-node chain scan before mining |
| **TX deduplication** | Gateway `seen_tx_ids` UUID set; duplicates return `BUY_FAILED` to the client |
| **Double-buy prevention** | `transfer_asset()` checks `asset_status == FOR_SALE` under `RLock` before writing; only the first buyer wins |
| **Account deletion safety** | Assets enter `PENDING_DELETION` (not hard-deleted) so in-flight purchases can complete before the blockchain window closes |
| **Public key collision** | `is_public_key_taken()` rejects wallet updates that would assign a public key already owned by a different active user |
| **Send concurrency** | `send_lock` on `Communication` prevents byte interleaving from concurrent senders |

---

## Python Engineering Highlights

### Object-Oriented Design

- **`ClientApp`** — central controller: page routing, state management, wallet session, background monitors. Pages are pure UI and call only `app.*` methods.
- **`ORM`** — encapsulates all database access behind a clean interface; no raw JSON manipulation in server handlers.
- **`GatewayServer`** — operation dispatch via `gateway_operations` and `blockchain_operations` dicts.
- **`BlockchainNode`** — self-contained per-node runtime: ledger, balances, peer sync, PoW mining.
- **`Communication`** — reusable encrypted socket wrapper shared by all four components.
- **Dataclasses** — `MarketplaceItem`, `Transaction`, `Block`, `ClientState`, `WalletData`, `UploadSession` all use `@dataclass` for clean field definitions.

### Threading

- **Daemon threads** — mining loops, recv loops, balance monitors, notification monitors, and bought-asset downloaders run as `daemon=True` threads and exit automatically with the main process.
- **`threading.RLock`** — used by the ORM for all JSON reads/writes (re-entrant so nested calls within the same thread don't deadlock).
- **`threading.Lock`** — `send_lock` and `recv_lock` on `Communication` for socket safety; `upload_lock` on the server for the in-progress upload session map.
- **`threading.Event`** — stop signal for mining threads; `stop_event.set()` causes the PoW loop to exit cleanly when another node wins.
- **`queue.Queue`** — decouples I/O threads from UI threads; `balance_queue`, `asset_sold_queue`, `notification_queue`, etc. all use `Queue` for thread-safe hand-off.

### Async / Flet event loop

`page.run_task(coroutine)` is used throughout `pages.py` for any UI mutation that originates from a background thread. All Flet widget updates (`page.overlay`, `dlg.open`, `page.update()`) stay on the main event loop while network I/O runs in threads.

### Type Hints

All public methods and data structures carry PEP 484 type hints. `from __future__ import annotations` enables forward references throughout.

### Dispatch Dicts

All four components route incoming messages via handler dicts rather than `if/elif` chains:

```python
# Server
self.handlers = {
    "LOGIN":                self.handle_login,
    "MOVE_TO_MARKETPLACE":  self.handle_move_to_marketplace,
    "BUY_ASSET":            self.handle_buy_asset,
    ...
}

# Gateway — separate dicts for server-side vs blockchain-side messages
self.gateway_operations    = {"upload_asset": self.handle_upload_asset, ...}
self.blockchain_operations = {"asset_signed_in_blockchain": self.handle_asset_signed_in_blockchain, ...}

# Bnode — threaded vs inline split
threaded_handlers = {"UPLOAD_ASSET": self.handle_mint_request, ...}
inline_handlers   = {"TX_REQUEST_BUY": self.handle_tx_request_buy, ...}
```

### Cryptography

All cryptographic operations use `cryptography.hazmat` primitives:

```python
# ECDSA signing (wallet)
sig = private_key.sign(payload_bytes, ec.ECDSA(hashes.SHA256()))

# ECDSA verification (gateway, per block)
pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(pk_hex))
pub.verify(bytes.fromhex(sig_hex), payload_bytes, ec.ECDSA(hashes.SHA256()))

# RSA-OAEP key transport
encrypted = rsa_pub.encrypt(aes_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), ...))

# AES-CBC message encryption
cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
```

---

## Directory Layout

```
aurex/
│
├── aurex_launcher.py              One-shot stack orchestrator (opens 4 terminals)
│
├── Blockchain/                    Blockchain nodes
│   ├── Bnode.py                   Node: PoW mining, ledger, peer sync, balances
│   └── node_<ip>_<port>/          Per-node runtime directory
│       ├── ledger.json            Full immutable chain
│       ├── balances.json          { public_key → AUR balance }
│       └── Node_keys/             RSA key pair for peer connections
│
├── Client/                        Desktop client
│   ├── client.py                  ClientApp controller, Client protocol, ImageCache
│   ├── pages.py                   All Flet UI pages (pure UI, no business logic)
│   ├── wallet_manager.py          ECDSA secp256k1 wallet (keygen, sign, load/save)
│   └── <username>/                Per-user runtime data (created on first login)
│       ├── wallet.json            ECDSA key pair (private key stays local)
│       └── cache/
│           ├── metadata.json      { asset_id → metadata } + balance
│           └── assets/            Cached image files (<asset_id>.<ext>)
│
├── DB/                            Server-side database (JSON files)
│   ├── users.json                 { username → user_dict }
│   ├── marketplace_items.json     { asset_id → asset_dict }
│   ├── notifications.json         { username → [pending messages] }
│   ├── pepper.txt                 Global password hash pepper (keep secret)
│   └── uploads/                   Sanitised uploaded images
│       └── <username>/            Per-user upload directory
│
├── Gateway/                       Gateway relay
│   ├── gateway.py                 GatewayServer (relay, validator, balance router)
│   ├── gateway_dashboard.py       Optional live dashboard UI
│   ├── GatewayKeys/               RSA keys for server connection
│   └── gateway_ledger.json        Block mirror for validation and dedup continuity
│
├── Server/                        Marketplace server
│   ├── server_module.py           Server: auth, ORM bridge, push events, gateway relay
│   ├── DB_ORM.py                  Thread-safe JSON ORM (users, assets, notifications)
│   └── ServerKeys/                RSA keys for client connections
│
└── SharedResources/               Shared across all four components
    ├── classes.py                 Communication, RSA_Client/Server, UDPServer/Client,
    │                              Transaction, Block, MarketplaceItem dataclasses
    ├── config.py                  Network addresses, ports, PoW difficulty, initial balance
    └── logging.py                 ANSI-coloured logger with configurable level
```
