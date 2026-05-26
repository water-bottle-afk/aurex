# Aurex — Blockchain Digital Marketplace

Aurex is a fully self-contained, peer-to-peer digital asset marketplace built on a custom blockchain. Users upload image assets, sign them with ECDSA keys, and the network mines them into an immutable ledger. Ownership is tracked on-chain; trades are signed and settled by the nodes.

---

## Architecture

Aurex follows a **star topology** with four components:

```
  [Client]  ──────────►  [Server]  ◄──────  [Gateway]  ◄──────►  [Bnode(s)]
```

| Component | Entry Point | Description |
|-----------|-------------|-------------|
| Client | `Client/client.py` | Flet desktop UI, wallet, protocol client |
| Server | `Server/server_module.py` | Auth, asset DB, push events, gateway relay |
| Gateway | `Gateway/gateway.py` | Blockchain relay, block validation, balance routing |
| Blockchain Node | `blockchain/Bnode.py` | PoW mining, ledger, balance accounting |

### Startup Order

1. Run blockchain node: `run_blockchain_node.bat`
2. Run gateway: `run_gateway.bat`
3. Run server: `run_server.bat`
4. Run client: `run_client.bat`

The gateway discovers nodes via UDP broadcast (`WHRSV`/`SRVAT` handshake on `GATEWAY_UDP_PORT`). The server connects to the gateway on startup and registers via `REGISTER_GATEWAY`.

---

## Protocol

All messages between components are JSON dicts with a `"type"` field (always UPPERCASE). Transport is encrypted with RSA+AES (see below).

### Client → Server

| Type | Purpose |
|------|---------|
| `START` | Initial handshake |
| `LOGIN` | Authenticate with username + password |
| `SIGNUP` | Register new account |
| `SEND_CODE` | Send password-reset OTP to email |
| `VERIFY_CODE` | Confirm OTP |
| `UPDATE_PASSWORD` | Change password (requires OTP code) |
| `UPDATE_PUBLIC_KEY` | Register ECDSA wallet public key |
| `UPLOAD_INIT` | Begin chunked file upload |
| `UPLOAD` | Send file chunk (base64) |
| `UPLOAD_FINISH` | Finalise upload, receive `asset_id` |
| `MOVE_TO_MARKETPLACE` | Trigger PoW mining + marketplace listing |
| `GET_ASSETS_IDS` | List asset IDs (marketplace or owned) |
| `GET_ASSET_BY_ID` | Streaming asset download |
| `BUY_ASSET` | Submit signed buy transaction |
| `UNLIST_ASSET` | Remove asset from marketplace |
| `DELETE_ASSET` | Delete own asset |
| `GET_BALANCE` | Request fresh balance from blockchain |
| `LOGOUT` | End session |

### Server → Client (push events)

These arrive asynchronously on the persistent connection. The client routes them by `_PUSH_EVENTS` into dedicated queues, never the response queue.

| Type | Meaning |
|------|---------|
| `BALANCE_IS` | Updated balance from blockchain |
| `FULLY_UPLOADED` | Asset mined and now FOR_SALE |
| `ASSET_LISTED` | Alias for `FULLY_UPLOADED` |
| `ASSET_UNLISTED` | Asset removed from marketplace |
| `BUY_SUCCESS` | Trade settled on-chain |
| `BUY_FAILED` | Transaction rejected |
| `BLOCK_ACCEPTED` | Sell transaction confirmed |
| `BLOCK_REJECTED` | Block rejected by nodes |
| `NOTIFICATION` | General server notification |

### Server ↔ Gateway

| Type | Direction | Purpose |
|------|-----------|---------|
| `REGISTER_GATEWAY` | G→S | Gateway registers on startup |
| `CREATE_BALANCE` | S→G→Nodes | Create initial wallet balance |
| `TX_REQUEST_BUY` | S→G→Nodes | Buy transaction for mining |
| `UPLOAD_ASSET` | S→G→Nodes | Asset mint PoW request |
| `UNLIST_ASSET` | S→G→Nodes | Unlist PoW request |
| `GET_BALANCE` | S→G→Nodes | Request balance for a public key |
| `SEND_BALANCE` | Nodes→G→S | Balance response |
| `BUY_SUCCESS` | Nodes→G→S | Confirmed buy |
| `ASSET_SIGNED_IN_BLOCKCHAIN` | Nodes→G | Minted block ready |
| `FULLY_UPLOAD` | G→S | Validated block; mark asset FOR_SALE |

### Asset Lifecycle

```
PENDING  →  (MOVE_TO_MARKETPLACE + PoW)  →  FOR_SALE
FOR_SALE →  (BUY_ASSET + PoW)            →  transferred to buyer (UNLISTED)
FOR_SALE →  (UNLIST_ASSET + PoW)         →  UNLISTED
```

---

## ORM — `Server/DB_ORM.py`

JSON-backed, thread-safe, no external ORM framework.

| File | Content |
|------|---------|
| `DB/users.json` | User accounts |
| `DB/marketplace_items.json` | All assets, keyed by owner username |
| `DB/notifications.json` | Pending notifications per user |
| `DB/uploads/<username>/` | Raw uploaded image files |
| `DB/pepper.txt` | Secret pepper for password hashing |

Key classes:

- **`User`** — username, email, salted+peppered password hash, ECDSA public key, OTP fields
- **`MarketplaceItem`** — asset_id, owner, name, description, file_type, cost, content_b64, storage_path, asset_status, version, public_key
- **`ORM`** — CRUD for users and marketplace items; includes `get_all_for_sale_assets()`, `transfer_asset()`, `update_asset_status()`, `find_asset_by_id()`

### Password Hashing

```
hash = SHA-256(PEPPER + password + salt)
```

Pepper is loaded from `DB/pepper.txt` at startup. Salt is per-user random hex. Password reset requires a 6-digit OTP sent by email, verified against a 5-minute expiry timestamp.

---

## ImageCache — `Client/client.py`

Per-user RAM + disk cache stored at `Client/<username>/cache/`.

```
Client/<username>/cache/
    metadata.json        ← balance + asset metadata
    assets/
        <asset_id>.png   ← cached image bytes
```

`metadata.json` layout:
```json
{
  "balance": 100.0,
  "<asset_id>": {
    "path": "assets/<asset_id>.png",
    "version": 2,
    "asset_name": "...",
    "owner": "...",
    "cost": 50.0,
    "asset_status": "FOR_SALE",
    "public_key": "..."
  }
}
```

Assets are re-fetched from the server only when `server_version > cached_version`. Balance is written whenever a `BALANCE_IS` push event arrives. The `"balance"` key is always present (initialised to `0.0` for new users).

---

## Wallet — `Client/wallet_manager.py`

ECDSA secp256k1 key pairs. The private key never leaves the client machine. The public key is registered with the server so the blockchain can verify signatures.

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

Signing:
```python
signature = private_key.sign(
    canonical_json_bytes(payload),   # sorted keys, compact separators
    ec.ECDSA(hashes.SHA256())
)
```

The gateway and blockchain nodes verify block signatures using the public key embedded in each block before they accept or relay it.

---

## RSA + AES Encryption — `SharedResources/classes.py`

Every connection (Client↔Server, Gateway↔Server, Bnode↔Gateway) uses a two-layer scheme:

1. **RSA handshake** — each peer has an RSA key pair in a `*Keys/` directory. On connect, both sides exchange public keys.
2. **AES session key** — one side generates a random AES-256 key, encrypts it with the peer's RSA public key, and sends it. All subsequent messages use AES-CBC with that session key.

Classes:
- `RSA_Server` — TCP server with RSA handshake per connection
- `RSA_Client` — TCP client that completes the RSA handshake
- `Communication` — wraps the socket with async send/recv queues over AES-encrypted framing
- `UDPServer` — listens for `WHRSV` UDP broadcast, replies `SRVAT|<ip>|<port>` for node discovery

---

## Proof of Work — `blockchain/Bnode.py`

Each node mines blocks with SHA-256 PoW. Difficulty is configured in `SharedResources/config.py`.

```python
while True:
    digest = sha256(canonical_json(block))
    if digest.startswith("0" * difficulty):
        block["hash"] = digest
        break
    block["nonce"] += 1
```

Transaction types mined on-chain:

| `tx_type` | Triggered by | Amount |
|-----------|--------------|--------|
| `ASSET_MINT` | `MOVE_TO_MARKETPLACE` | 0 AUR |
| `UNLIST_ASSET_FROM_BLOCKCHAIN` | `UNLIST_ASSET` | 0 AUR |
| `BUY` | `BUY_ASSET` | item price in AUR |

Node local storage:
```
blockchain/node_<ip>_<port>/
    ledger.json    ← full chain
    balances.json  ← public_key → AUR balance
    Node_keys/     ← RSA keys for peer connections
```

Nodes sync their ledger with peers via `GET_LEDGER` / `LEDGER_SNAPSHOT_*` chunked transfer when they detect they are behind by more than one block.

---

## Configuration — `SharedResources/config.py`

Central config for IP addresses, ports, PoW difficulty, initial balance, and UDP discovery interval. Edit this file to change the network topology.

---

## Key Directories

```
aurex/
├── blockchain/              Blockchain node + per-node data directories
├── Client/                  Flet desktop UI, wallet manager, image cache
│   └── <username>/          Per-user wallet file and asset cache
├── DB/                      JSON database files
│   └── uploads/<username>/  Raw uploaded images (named by SHA-256 hash)
├── Gateway/                 Gateway relay server
├── Server/                  Auth/marketplace server + ORM
├── SharedResources/         Config, logging, RSA+AES communication classes
├── run_server.bat           Launch server
├── run_gateway.bat          Launch gateway
├── run_blockchain_node.bat  Launch a blockchain node
└── run_client.bat           Launch desktop client
```
