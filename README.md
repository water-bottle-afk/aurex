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
┌──────────────────────────────────────────────────────────────┐
│                         AUREX NETWORK                        │
│                                                              │
│   [Client]  ←──AES/RSA──►  [Server]  ←──AES/RSA──►  [Gateway]  │
│    Flet UI                  Auth/DB                  Relay/Validator │
│    Wallet                   ORM                      Block verifier  │
│    ImageCache               Push events              PoW router      │
│                                 │                        │           │
│                                 └────────────────────────┘           │
│                                              │                       │
│                               ┌─────────────▼──────────────┐        │
│                               │     [Blockchain Nodes]      │        │
│                               │  Bnode × N  (PoW miners)   │        │
│                               │  ledger.json + balances.json│        │
│                               └─────────────────────────────┘        │
└──────────────────────────────────────────────────────────────┘
```

| Component | Entry Point | Role |
|-----------|-------------|------|
| **Client** | `Client/client.py` | Flet desktop UI, ECDSA wallet, per-user image cache, server protocol client |
| **Server** | `Server/server_module.py` | Authentication, JSON ORM, asset storage, push-event broker, gateway relay |
| **Gateway** | `Gateway/gateway.py` | Stateless relay between server and nodes; validates mined blocks; routes balance queries to the longest-chain node |
| **Blockchain Node (Bnode)** | `blockchain/Bnode.py` | SHA-256 PoW mining, immutable ledger, AUR balance accounting, peer-to-peer ledger sync |

---

## Component Reference

### Client (`Client/`)

- Full Flet desktop UI (dark gold theme, multiple pages)
- RSA+AES encrypted TCP connection to the server (`Client` class wraps `RSA_Client`)
- Async receive/send queue model: a background thread routes push events into dedicated queues so the UI thread is never blocked on I/O
- ECDSA secp256k1 wallet: private key stays local; public key registered with the server
- Per-user disk cache (`ImageCache`) — stores asset images and metadata, balance persistence between sessions
- `ClientApp` (Flet `app()` entry) owns all state and drives page navigation via route changes

### Server (`Server/`)

- `RSA_Server` subclass; one thread per connected client
- JSON-backed ORM (`DB_ORM.ORM`) — no external database
- Handles all client protocol messages (login, upload, buy, etc.)
- Acts as gateway bridge: forwards blockchain tasks to the gateway and pushes results back to the right client
- Sends server-push events (`FULLY_UPLOADED`, `BUY_SUCCESS`, `BALANCE_IS`, etc.) to connected clients via `push_event()`
- Password hashing: SHA-256(pepper + password + salt); OTP reset via SMTP email

### Gateway (`Gateway/gateway.py`)

- Stateless relay — holds **no** asset data, **no** user accounts
- Maintains a `gateway_ledger.json` purely for block index/prev_hash continuity checking
- Deduplicates transactions with `seen_tx_ids` (UUID set) and prevents double-minting with `seen_minted_asset_ids`
- Routes `GET_BALANCE` only to the node with the longest chain (prevents duplicate responses)
- Validates mined blocks (hash integrity + PoW target) before broadcasting to peers
- Triggers ledger sync (`GET_LEDGER`) for nodes that fall behind
- Discovered by nodes via UDP broadcast (`WHRSV` → `SRVAT|<ip>|<port>`)

### Blockchain Node (`blockchain/Bnode.py`)

- Discovers gateway via UDP broadcast; registers with `REGISTER_BLOCKCHAIN_NODE`
- Mines SHA-256 PoW blocks in a separate **daemon thread** per task (never blocks the gateway listener)
- Maintains a full `ledger.json` (chain) and `balances.json` (public key → AUR) per node directory
- Peer-to-peer ledger sync: chunks the chain and streams it to lagging nodes via `LEDGER_SNAPSHOT_*` messages
- Node keys stored in `Node_keys/` (RSA key pair for peer connections)
- Stops mining immediately when it receives `BROADCAST_TX_TO_VERIFY` (another node won)

---

## Startup

### One-shot launcher (recommended)

```
python aurex_launcher.py [--debug-level DEBUG|INFO|WARNING|ERROR]
```

Opens four separate `cmd` windows in order:

| Window | Process |
|--------|---------|
| `Aurex-Nodes` | Blockchain node on port 14253 |
| `Aurex-Gateway` | Gateway (waits 2 s for nodes) |
| `Aurex-Marketplace` | Server (waits 3 s for gateway) |
| `Aurex-Client` | Flet desktop app |

### Manual order

```
# Terminal 1 — blockchain node
cd blockchain
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

**First-time setup**: after login, go to **Settings → Wallet & Identity → Generate New Wallet** before uploading assets.

---

## Protocol Reference

All messages are JSON dicts with a `"type"` field (always `UPPER_SNAKE_CASE`). Transport is RSA-handshaked + AES-CBC encrypted (see [Security Model](#security-model)).

### Client → Server

| Type | Purpose |
|------|---------|
| `LOGIN` | Authenticate (username + password) |
| `SIGNUP` | Register new account (username, password, email) |
| `SEND_CODE` | Request 6-digit OTP to email for password reset |
| `VERIFY_CODE` | Submit OTP; receive confirmation before reset |
| `UPDATE_PASSWORD` | Set new password (requires valid OTP) |
| `UPDATE_PUBLIC_KEY` | Register/update ECDSA wallet public key |
| `UPLOAD_INIT` | Begin chunked upload (metadata + upload_id) |
| `UPLOAD` | Send file chunk (base64-encoded) |
| `UPLOAD_FINISH` | Finalise upload; receive `asset_id` |
| `MOVE_TO_MARKETPLACE` | Trigger PoW mining to list an asset (`PENDING`→MINT or `UNLISTED`→LIST) |
| `GET_ASSETS_IDS` | List asset IDs — marketplace (no username) or owned (with username) |
| `GET_ASSET_BY_ID` | Streaming asset download (metadata + chunked image) |
| `BUY_ASSET` | Submit signed buy transaction |
| `UNLIST_ASSET` | Remove an asset from the marketplace via PoW |
| `DELETE_ASSET` | Delete own asset from DB and disk |
| `GET_BALANCE` | Request fresh AUR balance from blockchain |
| `LOGOUT` | End session |
| `DELETE_ACCOUNT` | Permanently remove account and all assets |

### Server → Client (push events)

Arrive asynchronously on the persistent connection. The client routes them by type into dedicated queues and never puts them in the request/response queue.

| Type | Meaning |
|------|---------|
| `BALANCE_IS` | Updated AUR balance from blockchain |
| `FULLY_UPLOADED` | Asset mined and now `FOR_SALE` |
| `ASSET_LISTED` | Alias for `FULLY_UPLOADED` |
| `ASSET_UNLISTED` | Asset removed from marketplace (owner's copy) |
| `ASSET_REMOVED` | Asset no longer on marketplace (all users) |
| `ASSET_SOLD` | Owner's asset was purchased by another user |
| `BUY_SUCCESS` | Trade settled on-chain (buyer receives this) |
| `BUY_FAILED` | Transaction rejected (insufficient balance, duplicate, etc.) |
| `BLOCK_ACCEPTED` | Sell transaction confirmed |
| `BLOCK_REJECTED` | Block rejected by nodes |
| `NOTIFICATION` | General server notification string |

### Server ↔ Gateway

| Type | Direction | Purpose |
|------|-----------|---------|
| `REGISTER_GATEWAY` | G→S | Gateway announces itself on startup |
| `CREATE_BALANCE` | S→G→Nodes | Create initial 100 AUR balance for new user |
| `UPLOAD_ASSET` | S→G→Nodes | Mint a new asset (PENDING status) — triggers `ASSET_MINT` PoW |
| `LIST_ASSET` | S→G→Nodes | Re-list an unlisted asset — triggers `LIST_ASSET` PoW (no re-mint) |
| `UNLIST_ASSET` | S→G→Nodes | Remove asset from marketplace — triggers `UNLIST_ASSET_FROM_BLOCKCHAIN` PoW |
| `TX_REQUEST_BUY` | S→G→Nodes | Buy transaction — triggers `BUY` PoW |
| `GET_BALANCE` | S→G→Node | Request AUR balance (routed to longest-chain node only) |
| `SEND_BALANCE` | Nodes→G→S | Balance response from node |
| `BUY_SUCCESS` | Nodes→G→S | Confirmed buy block |
| `ASSET_SIGNED_IN_BLOCKCHAIN` | Nodes→G | MINT block ready |
| `ASSET_UNLIST_SIGNED_IN_BLOCKCHAIN` | Nodes→G | UNLIST block ready |
| `ASSET_LIST_SIGNED_IN_BLOCKCHAIN` | Nodes→G | LIST block ready (re-listing) |
| `FULLY_UPLOAD` | G→S | Validated MINT/LIST block; mark asset `FOR_SALE` |
| `ASSET_UNLISTED` | G→S | Validated UNLIST block; mark asset `UNLISTED` |
| `BROADCAST_TX_TO_VERIFY` | G→Nodes | Winning block; all other nodes stop mining and apply it |

### Node ↔ Node (peer sync)

| Type | Purpose |
|------|---------|
| `GET_LEDGER` | Request chain from a peer that is ahead |
| `LEDGER_SNAPSHOT_BEGIN` | Start of chunked chain transfer |
| `LEDGER_SNAPSHOT_CHUNK` | Chunk of ledger blocks |
| `LEDGER_SNAPSHOT_END` | End of transfer |
| `GET_BALANCE` (peer variant) | Request balance table from a peer |

---

## Asset Lifecycle

```
            ┌─────────┐
            │ PENDING │  ← asset uploaded, not yet on-chain
            └────┬────┘
                 │ MOVE_TO_MARKETPLACE  (PENDING path)
                 │ → Gateway broadcasts UPLOAD_ASSET
                 │ → Nodes mine ASSET_MINT tx
                 ▼
           ┌──────────┐
           │ FOR_SALE │  ← on-chain, visible in marketplace
           └────┬─────┘
       ┌────────┼──────────────┐
       │        │              │
       │  UNLIST_ASSET    BUY_ASSET
       │  → UNLIST_ASSET  → BUY tx mined
       │    tx mined       → ownership transferred
       ▼                   → original owner: asset removed
  ┌──────────┐             → buyer: asset appears in My Assets
  │ UNLISTED │
  └────┬─────┘
       │ MOVE_TO_MARKETPLACE  (UNLISTED path)
       │ → Gateway broadcasts LIST_ASSET
       │ → Nodes mine LIST_ASSET tx  (no re-mint)
       ▼
  ┌──────────┐
  │ FOR_SALE │  ← back on marketplace
  └──────────┘
```

Transaction types written to the blockchain:

| `tx_type` | Triggered by | AUR transfer |
|-----------|--------------|--------------|
| `ASSET_MINT` | `MOVE_TO_MARKETPLACE` (first time) | 0 AUR |
| `LIST_ASSET` | `MOVE_TO_MARKETPLACE` (re-list) | 0 AUR |
| `UNLIST_ASSET_FROM_BLOCKCHAIN` | `UNLIST_ASSET` | 0 AUR |
| `BUY` | `BUY_ASSET` | price in AUR (buyer → seller) |

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

Difficulty is set globally in `config.py` (`POW_DIFFICULTY = 3` by default).

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

### Local storage

```
blockchain/node_<ip>_<port>/
    ledger.json        ← full immutable chain
    balances.json      ← { "04ab...ff": 75.0, ... }
    Node_keys/         ← RSA key pair for peer handshakes
```

### Double-mint guard (two layers)

1. **Node layer** — `handle_mint_request` scans `self.chain` before mining; if the `asset_id` already has an `ASSET_MINT` block, it skips silently.
2. **Gateway layer** — `seen_minted_asset_ids` (populated from `gateway_ledger.json` on startup) rejects any `UPLOAD_ASSET` request whose `asset_id` was already minted. The gateway also deduplicates incoming mined blocks.

### Mining concurrency model

Each mining task runs in a **daemon thread** (`threading.Thread(..., daemon=True)`). The gateway listener loop continues to receive messages while mining is in progress. When `BROADCAST_TX_TO_VERIFY` arrives (another node won), the thread's `mine()` method exits early via a stop flag.

---

## Gateway

The gateway is **stateless with respect to user data** — it never reads or writes the asset database. Its only persisted state is `gateway_ledger.json` (a mirror of mined blocks used for block validation).

Key responsibilities:

| Responsibility | Mechanism |
|---------------|-----------|
| TX deduplication | `seen_tx_ids: set[str]` — UUID set per session |
| Mint deduplication | `seen_minted_asset_ids: set[str]` — persisted to ledger on startup |
| Block validation | Hash integrity + PoW target check in `verify_mined_block()` |
| Balance routing | `best_node_addr()` — routes `GET_BALANCE` to the node with the longest chain |
| Lagging node sync | Sends `GET_LEDGER` to any node whose chain length falls behind the publisher |
| Node discovery | UDP `UDPServer` replies `SRVAT|<ip>|<port>` to `WHRSV` broadcasts |

---

## Server & ORM

### JSON ORM (`Server/DB_ORM.py`)

No external database. All persistence is thread-safe JSON file I/O via `threading.RLock()`.

| File | Content |
|------|---------|
| `DB/users.json` | User accounts (username, email, salt, password hash, public key, OTP fields) |
| `DB/marketplace_items.json` | All assets keyed by owner username |
| `DB/notifications.json` | Pending push notifications per user |
| `DB/uploads/<username>/` | Raw uploaded image files (named by content hash) |
| `DB/pepper.txt` | Secret pepper loaded once at startup for password hashing |

Key ORM methods:

| Method | Purpose |
|--------|---------|
| `get_user(username)` | Fetch user record |
| `create_user(...)` | Insert user with hashed password |
| `verify_password(...)` | SHA-256(pepper + pw + salt) comparison |
| `find_asset_by_id(asset_id)` | Scan all owners to locate an asset |
| `get_all_for_sale_assets()` | Return all `FOR_SALE` assets for the marketplace |
| `get_assets_for_user(username)` | Return user's non-FOR_SALE assets (My Assets) |
| `transfer_asset(asset_id, from, to)` | Atomically move asset between owner buckets |
| `update_asset_status(asset_id, status)` | Change lifecycle status; optionally increments version |
| `delete_asset(asset_id, owner)` | Remove asset record from DB |
| `delete_user_assets(username)` | Remove all assets for a user |
| `queue_notification(username, msg)` | Persist notification for offline user |
| `flush_notifications(username)` | Return and clear pending notifications |

### Password hashing

```
hash = SHA-256( pepper + plaintext_password + salt )
```

- **pepper** — global secret in `DB/pepper.txt`, never stored alongside the hash
- **salt** — per-user random hex string stored in `users.json`
- **OTP reset** — 6-digit code, sent via SMTP, expires after 5 minutes

### Image sanitisation

Uploaded images are re-rendered through Pillow (`PIL.Image`) before being saved to disk. This strips all metadata, EXIF data, embedded scripts, and steganographic payloads. If Pillow is not installed, a magic-byte check is applied as a fallback.

---

## Client — UI, Cache, Wallet

### Pages (`Client/pages.py`)

| Route | Page |
|-------|------|
| `/login` | Sign-in form |
| `/signup` | Account registration |
| `/forgot` | Three-step password reset (email → OTP → new password) |
| `/settings` | Wallet management, account deletion |
| `/marketplace` | Browse and buy `FOR_SALE` assets |
| `/upload` | Mint a new asset (`PENDING` → mining) |
| `/my_assets` | View owned assets; re-list or delete |
| `/notifications` | History of server push events |

### Image cache (`Client/client.py` — `ImageCache`)

```
Client/<username>/cache/
    metadata.json        ← balance + per-asset metadata dict
    assets/
        <asset_id>.<ext> ← downloaded image bytes
```

- Assets are re-fetched only when `server_version > cached_version`
- Balance is persisted to `metadata.json` on every `BALANCE_IS` push event and loaded on login so the UI shows a value instantly before the fresh blockchain query completes
- Old cache formats are detected and migrated automatically on startup

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

Signing any transaction payload:
```python
canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
signature = private_key.sign(canonical, ec.ECDSA(hashes.SHA256()))
```

The gateway verifies ECDSA signatures on each block before accepting it. The public key is embedded in every block so nodes can verify without a separate lookup.

### Gateway offline state

`ClientApp` tracks `gateway_online: bool | None`:
- `None` — unknown (initial state after login)
- `True` — confirmed online (any gateway operation succeeded)
- `False` — confirmed offline (server returned "Gateway Server isn't online")

When offline, a warning banner appears on the Marketplace page, and buy/unlist/upload-to-marketplace actions are blocked with a clear error message. The cached AUR balance is used as a fallback when `GET_BALANCE` fails.

---

## Shared Resources

### `SharedResources/classes.py`

#### `Communication`

Wraps a TCP socket with:
- **AES-CBC encryption** — all messages encrypted after RSA handshake
- **2-byte length framing** — `struct.pack('!H', len(msg))` prefix, so any message size up to 65535 bytes is supported
- **Async duplex queues** — `start_async()` spawns a recv thread (feeds `msg_queue`) and a send thread (drains `send_queue`), so I/O never blocks the caller
- **Thread-safe sends** — `send_lock` (`threading.Lock`) prevents concurrent `sendall` calls from interleaving bytes
- **Thread-safe recvs** — `recv_lock` (`threading.Lock`) prevents concurrent `recv_one_message` calls from interleaving the length header with the payload

#### `RSA_Server` / `RSA_Client`

Handshake protocol on every new connection:

```
Client                            Server
  ──── SEND_PUBLIC_KEY ──────────►
  ◄─── GET_PUBLIC_KEY (RSA pub) ──
  ──── GET_SYMETRIC_KEY ─────────►  (AES key encrypted with RSA-OAEP)
  ◄─── OK ────────────────────────  (all subsequent messages AES-encrypted)
```

RSA keys are stored in `*Keys/` directories relative to each component and reused across restarts.

#### `UDPServer` / `UDPClient`

Simple UDP broadcast discovery: nodes broadcast `WHRSV` on the LAN; the gateway `UDPServer` replies `SRVAT|<ip>|<port>` so nodes know where to connect.

#### `Transaction` / `Block` (dataclasses)

Lightweight dataclasses used by the blockchain. `Block.compute_hash()` serialises with `json.dumps(asdict(block), sort_keys=True)` for deterministic hashing.

#### `MarketplaceItem` (dataclass)

Shared between server, gateway, and client. `from_dict()` includes a migration path for old `blockchain_status`/`for_sale` field names.

### `SharedResources/config.py`

Single source of truth for all network addresses, ports, PoW difficulty, and initial balance. Change it once to reconfigure the whole network.

```python
SERVER_IP,  SERVER_PORT          = "10.100.102.58", 55554
GATEWAY_IP, GATEWAY_BLOCKCHAIN_PORT = "10.100.102.58", 33334
GATEWAY_UDP_PORT                 = 22222
POW_DIFFICULTY                   = 3
INITIAL_BALANCE                  = 100
```

### `SharedResources/logging.py`

ANSI-coloured log output:
- `DEBUG` → green
- `INFO` → light blue
- `WARNING` → orange
- `ERROR` → red

---

## Security Model

| Layer | Mechanism |
|-------|-----------|
| **Transport encryption** | RSA-2048-OAEP key exchange, then AES-128-CBC for all messages |
| **Message integrity** | 2-byte length framing; JSON parse errors silently drop the message |
| **Asset ownership** | ECDSA secp256k1 signatures — every tx payload is signed by the owner's private key |
| **Block integrity** | SHA-256 hash of the full block dict (canonical JSON, sorted keys); PoW target enforced by gateway before broadcast |
| **Password storage** | SHA-256(pepper + password + salt) — pepper never stored with the hash |
| **OTP reset** | 6-digit random code, 5-minute expiry, sent via SMTP; verified before password change |
| **Image sanitisation** | PIL re-render strips EXIF, metadata, and embedded payloads before disk storage |
| **Double-mint prevention** | Two-layer: gateway `seen_minted_asset_ids` set + per-node chain scan before mining |
| **TX deduplication** | Gateway `seen_tx_ids` UUID set; duplicates return `BUY_FAILED` to the client |
| **Send concurrency** | `send_lock` on `Communication` prevents byte interleaving from concurrent senders |
| **Recv concurrency** | `recv_lock` on `Communication` prevents frame corruption from concurrent readers |

---

## Python Engineering Highlights

### Object-Oriented Design

- **`ClientApp`** — central controller with page routing, state, wallet session, background monitors. All UI actions go through methods; pages only call `app.*`.
- **`ORM`** — encapsulates all DB access behind a clean interface; no raw JSON in handlers.
- **`GatewayServer`** — operation dispatch via `gateway_operations` and `blockchain_operations` dicts (not if/elif chains).
- **`BlockchainNode`** — self-contained per-node runtime: ledger, balances, peer sync, mining.
- **`Communication`** — reusable encrypted socket wrapper shared by all four components.
- **Dataclasses** — `MarketplaceItem`, `Transaction`, `Block`, `ClientState`, `WalletData` all use `@dataclass` for clean field definitions and `asdict()` serialisation.
- **Inheritance** — `Server` subclasses `RSA_Server`; the gateway's node listener does the same.

### Threading

- **Daemon threads** — mining, recv loops, balance monitors, notification monitors, bought-asset downloaders all run as `threading.Thread(..., daemon=True)` so they exit automatically when the main process ends.
- **`threading.RLock`** — used by the ORM for all JSON file reads/writes (re-entrant so nested calls within the same thread don't deadlock).
- **`threading.Lock`** — `send_lock` and `recv_lock` on `Communication` for socket safety; `nodes_lock` on the gateway for the connected-nodes dict.
- **`threading.Event`** — used as a stop signal for mining; `stop_event.set()` causes the mining loop to exit cleanly.
- **`queue.Queue`** — decouples I/O threads from UI threads; `msg_queue`, `send_queue`, `balance_queue`, `asset_sold_queue`, etc. all use `Queue` for thread-safe hand-off.

### Async / Flet event loop

The Flet `page.run_task(coroutine)` API is used throughout `pages.py` for any UI mutation that originates from a background thread. This keeps all Flet widget updates on the main event loop while network I/O runs in threads.

### Type Hints

All public methods and data structures use PEP 484 type hints:

```python
def get_if_current(self, asset_id: str, server_version: int) -> "tuple[dict, bytes] | None": ...
def best_node_addr(self) -> "tuple[str, int] | None": ...
def handle_upload_asset(self, request: dict, comm=None) -> None: ...
nodes: dict[tuple[str, int], dict[str, Any]]
```

`from __future__ import annotations` enables forward references throughout.

### List Comprehensions and Generators

```python
# Filter and normalise asset IDs from a server response
entries = [
    entry if isinstance(entry, dict) else {"id": str(entry), "version": 1}
    for entry in resp.get("ids", [])
]

# Collect all FOR_SALE assets across all owners
items = [
    MarketplaceItem.from_dict(a)
    for assets in market.values()
    for a in assets
    if isinstance(a, dict) and a.get("asset_status") == "FOR_SALE"
]

# Double-mint check (generator expression — short-circuits on first match)
already_minted = any(
    isinstance(b.get("tx"), dict)
    and b["tx"].get("tx_type") == "ASSET_MINT"
    and b["tx"].get("asset_id") == asset_id
    for b in self.chain
)
```

### Context Managers

- `with self.lock:` / `with self.recv_lock:` around all socket operations
- `with self.nodes_lock:` around gateway node dict mutations
- `Path(...).read_bytes()` / `.write_text()` — context-free pathlib I/O (handles open/close internally)

### Pathlib

`pathlib.Path` is used throughout instead of `os.path`:

```python
PROJECT_ROOT = Path(__file__).resolve().parent.parent
self._cache_dir = PROJECT_ROOT / "Client" / username / "cache"
self._metadata_path = self._cache_dir / "metadata.json"
storage_path = Path(asset.storage_path)
```

### Dispatch Dicts

Instead of long `if/elif` chains, all components use handler dicts:

```python
# Server
self.handlers = {
    "LOGIN": self.handle_login,
    "MOVE_TO_MARKETPLACE": self.handle_move_to_marketplace,
    ...
}

# Gateway — separate dicts for server-side and blockchain-side messages
self.gateway_operations = {"upload_asset": self.handle_upload_asset, ...}
self.blockchain_operations = {"asset_signed_in_blockchain": self.handle_asset_signed_in_blockchain, ...}

# Bnode — threaded vs inline split
threaded_handlers = {"UPLOAD_ASSET": self.handle_mint_request, "LIST_ASSET": self.handle_list_request, ...}
inline_handlers   = {"TX_REQUEST_BUY": self.handle_tx_request_buy, ...}
```

### Cryptography Library

All cryptographic operations use `cryptography.hazmat` primitives:

```python
# ECDSA signing (wallet)
from cryptography.hazmat.primitives.asymmetric import ec
sig = private_key.sign(payload_bytes, ec.ECDSA(hashes.SHA256()))

# ECDSA verification (gateway)
pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256K1(), bytes.fromhex(pk_hex))
pub.verify(bytes.fromhex(sig_hex), payload_bytes, ec.ECDSA(hashes.SHA256()))

# RSA-OAEP key transport
encrypted = rsa_pub.encrypt(aes_key, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), ...))
aes_key   = rsa_priv.decrypt(ciphertext, padding.OAEP(...))

# AES-CBC message encryption
cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
```

---

## Directory Layout

```
aurex/
│
├── aurex_launcher.py          One-shot stack orchestrator
│
├── blockchain/                Blockchain nodes
│   ├── Bnode.py               Node implementation (PoW, ledger, peer sync)
│   └── node_<ip>_<port>/      Per-node runtime data
│       ├── ledger.json        Full immutable chain
│       ├── balances.json      Public key → AUR balance map
│       └── Node_keys/         RSA key pair for peer connections
│
├── Client/                    Desktop client
│   ├── client.py              ClientApp controller, Client protocol, ImageCache
│   ├── pages.py               All Flet UI pages (pure UI, no business logic)
│   ├── wallet_manager.py      ECDSA secp256k1 wallet (keygen, sign, load/save)
│   └── <username>/            Per-user runtime data
│       ├── wallet.json        ECDSA key pair (private key stays local)
│       └── cache/
│           ├── metadata.json  Balance + asset metadata cache
│           └── assets/        Cached image files
│
├── DB/                        Server database
│   ├── users.json             User accounts
│   ├── marketplace_items.json Assets keyed by owner username
│   ├── notifications.json     Pending push notifications
│   ├── pepper.txt             Password hash pepper (keep secret)
│   └── uploads/               Raw uploaded images
│       └── <username>/        Per-user upload directory
│
├── Gateway/                   Gateway relay
│   ├── gateway.py             GatewayServer (relay, validator, balance router)
│   ├── gateway_dashboard.py   Optional GUI dashboard
│   ├── GatewayKeys/           RSA keys for server connection
│   └── gateway_ledger.json    Block mirror for validation continuity
│
├── Server/                    Marketplace server
│   ├── server_module.py       Server (auth, ORM bridge, push events, gateway relay)
│   ├── DB_ORM.py              Thread-safe JSON ORM
│   └── ServerKeys/            RSA keys for client connections
│
└── SharedResources/           Shared across all components
    ├── classes.py             Communication, RSA_Client/Server, UDPServer/Client,
    │                          Transaction, Block, MarketplaceItem dataclasses
    ├── config.py              Network addresses, ports, PoW difficulty, initial balance
    └── logging.py             ANSI-coloured logger with configurable level
```
