# Run Example Transaction (RPC + 3 Nodes)

Follow these steps to see a transaction go through: RPC broadcast → nodes mine → one node wins → block confirmed → server updates wallets (alice → bob 10 coins).

---

## 0. (Once) Seed alice and bob + wallets

From project root or `python_files`:

```bash
cd c:\dev\aurex\python_files
python seed_alice_bob.py
```

This creates users **alice** and **bob** in `DB/marketplace.db` and wallets: alice 100 coins, bob 0.

---

## 1. Start 3 nodes (first)

Open a terminal and run the launcher with **3 nodes** and **difficulty 2** (so mining finishes quickly):

```bash
cd c:\dev\aurex\blockchain
python launcher.py --nodes 3 --difficulty 2
```

- Three **new CMD windows** will open (PoW Node 1, 2, 3). **Leave them open.**
- In each node window you should see logs like:
  - `node started port=13245 ...`
  - `listening on 0.0.0.0:13245`
- The launcher terminal will say "Running - press Ctrl+C to stop". Leave it running.

---

## 2. Start the gateway server (second terminal)

Open a **new** terminal:

```bash
cd c:\dev\aurex\blockchain
python gateway_server.py
```

You should see:

- `Gateway server starting ... submit_transaction -> nodes [13245, 13246, 13247, ...]`
- `Gateway listening on 0.0.0.0:5000 ...`

Leave this terminal open.

---

## 3. Submit the example transaction (third terminal)

Open **another** terminal and run the test script:

```bash
cd c:\dev\aurex\blockchain
python test_transaction.py
```

You should see the transaction payload and the RPC response (e.g. `nodes_reached: 3`).

---

## 4. (Optional) Start the marketplace server

If you want wallet updates (alice −10, bob +10) when the block is confirmed, start the server so it listens for block confirmations on port 23457:

```bash
cd c:\dev\aurex\python_files
python server_moudle.py
```

Then when a block is confirmed, the server will log "Saved: Transferred 10 from alice to bob" and update balances.

---

## 5. What to watch in the logs

- **Node windows (1, 2, 3):**
  - `gossip: NEW_TRANSACTION received sender=alice`
  - `hashing: mining started difficulty=2`
  - **One** node will then log:
    - `block mined index=0 hash=00...`
    - `gossip: block broadcast to 2 peers`
    - `block_confirmation sent to RPC block_index=0`
  - The **other two** nodes will log:
    - `validation: PoW ok block_index=0`
    - `validation: signature ok`
    - `validation: chain ok prev_hash link`
    - `gossip: block accepted index=0 hash=00...`

- **Gateway terminal:**
  - `=== TRANSACTION SUBMITTED === timestamp=... sender=alice data=...`
  - `broadcast tx to node port=13245` (and 13246, 13247)
  - `=== TRANSACTION CONFIRMED (block committed) === block_index=0 ...`
  - `Saved to ledger: block_index=0`
  - `notified server: block_confirmation block_index=0`

- **Server terminal** (if running): `Block confirmed: index=0 ...` then `Saved: Transferred 10 from alice to bob` and balance logs.

That’s the full path: **transaction → RPC → nodes → mining → one node wins → block broadcast → others accept → RPC gets block_confirmation → server updates wallets.**

---

## Optional: Run server block-confirmation listener

If the marketplace server is running and listening on **port 23457** for block confirmations, it will also log the confirmation.  
Config: `blockchain/config.py` has `SERVER_NOTIFY_PORT = 23457`; `python_files/config.py` has `BLOCK_CONFIRMATION_PORT = 23457`.

---

## Troubleshooting

- **"Could not connect to RPC"**  
  Start `gateway_server.py` first and wait until it prints "Gateway listening on ...".

- **"Transaction sent to 0/3 nodes"**  
  Start the 3 nodes (launcher) and wait until each window shows "listening on ...".

- **No "block mined" in any node**  
  Use `--difficulty 2`; higher difficulty will take much longer.
